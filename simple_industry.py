import os
from pyomo.environ import *

dependencies = "switch_model.timescales", "switch_model.balancing.load_zones"
optional_dependencies = "switch_model.transmission.local_td"

def define_components(mod):
    # 原有的组件定义保持不变
    mod.dr_shift_down_limit = Param(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        default=0.0,
        within=NonNegativeReals,
        validate=lambda m, value, z, t: value <= m.zone_demand_mw[z, t],
    )
    mod.dr_shift_up_limit = Param(
        mod.LOAD_ZONES, mod.TIMEPOINTS, default=float("inf"), within=NonNegativeReals
    )

    # 添加新的参数
    mod.response_time = Param(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        default=1.0,  # 默认响应时间为1小时
        within=NonNegativeReals
    )

    mod.recovery_time = Param(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        default=2.0,  # 默认恢复时间为2小时
        within=NonNegativeReals
    )

    # 修改决策变量
    mod.ShiftDemand = Var(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        within=Reals,
        bounds=lambda m, z, t: (
            (-1.0) * m.dr_shift_down_limit[z, t],
            m.dr_shift_up_limit[z, t],
        ),
    )

    def recovery_constraint_rule(m, z, t):
        # 获取响应前和响应期间的负荷水平
        original_demand = m.zone_demand_mw[z, t]  # 响应前的负荷水平 a
        reduced_demand = m.ShiftDemand[z, t] + original_demand  # 响应期间的负荷水平 b
        
        if m.recovery_time[z, t] > 0:
            # 计算每个时间点的负荷增加量，使其在恢复时间内线性增长
            recovery_increase_per_period = (original_demand - reduced_demand) / m.recovery_time[z, t]
            return m.ShiftDemand[z, t] == recovery_increase_per_period
        else:
            return Constraint.Feasible

    mod.Recovery_Constraint = Constraint(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        rule=recovery_constraint_rule
    )

    mod.is_DR_active = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=Binary)
    mod.dr_shift_down_active = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals)

    def dr_shift_down_active_upper_bound_rule(m, z, t):
        return m.dr_shift_down_active[z, t] <= m.dr_shift_down_limit[z, t] * m.is_DR_active[z, t]

    mod.DR_Shift_Down_Active_UB_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_shift_down_active_upper_bound_rule)

    def dr_shift_down_active_lower_bound_rule(m, z, t):
        return m.dr_shift_down_active[z, t] >= m.ShiftDemand[z, t]

    mod.DR_Shift_Down_Active_LB_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_shift_down_active_lower_bound_rule)

    mod.shift_demand_abs = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals)

    def shift_demand_abs_rule1(m, z, t):
        return m.shift_demand_abs[z, t] >= m.ShiftDemand[z, t]

    def shift_demand_abs_rule2(m, z, t):
        return m.shift_demand_abs[z, t] >= -m.ShiftDemand[z, t]

    mod.Shift_Demand_Abs_Constraint1 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule1)
    mod.Shift_Demand_Abs_Constraint2 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule2)

    def dr_activation_rule(m, z, t):
        return m.dr_shift_down_active[z, t] >= m.shift_demand_abs[z, t] - 1e-6

    mod.DR_Activation_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_activation_rule)


    '''
    def dr_activation_rule(m, z, t):
        # 确保在需求响应期间，is_DR_active为1，否则为0
        return m.is_DR_active[z, t] * m.dr_shift_down_limit[z, t] >= m.ShiftDemand[z, t] * 0.999
    
    def dr_activation_rule(m, z, t):
        shift_demand_value = value(m.ShiftDemand[z, t])
        abs_shift_demand_value = abs(shift_demand_value)
        if abs_shift_demand_value == 0:
            return m.is_DR_active[z, t] == 0
        else:
            return m.is_DR_active[z, t] == 1
    '''

    #mod.DR_Activation_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_activation_rule)

    '''
    def dr_min_interval_rule(m, z, t):
        # 检查当前时间点 t 是否在典型天的开始（即每个典型天的第1个小时）
        if (t - 1) % 24 == 0:
            # 如果是典型天的开始，检查前一个典型天的最后三个小时
            valid_indices = [t - i for i in range(22, 25)]  # 典型天的最后三个小时
        else:
            # 如果不是典型天的开始，检查当前典型天的前两个小时
            valid_indices = [t - i for i in range(1, 4) if t - i > 0]
    
        # 确保在有效时间点内，需求响应的激活次数不超过1次
        return sum(m.is_DR_active[z, ti] for ti in valid_indices) <= 1
    '''
    
    def dr_min_interval_rule(m, z, t):
        # 确保 t - i 在有效的时间点范围内
        valid_indices = [t - i for i in range(1, 4) if t - i >= 1]  # 从1开始的时间点
        if valid_indices:  # 如果 valid_indices 不为空
            return sum(m.is_DR_active[z, ti] for ti in valid_indices) <= 1
        else:
            return Constraint.Feasible

    mod.DR_Min_Interval_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_min_interval_rule)

    
    mod.DR_Shift_Net_Zero = Constraint(
        mod.LOAD_ZONES,
        mod.TIMESERIES,
        rule=lambda m, z, ts: sum(m.ShiftDemand[z, t] for t in m.TPS_IN_TS[ts]) == 0.0,
    )

    try:
        mod.Distributed_Power_Withdrawals.append("ShiftDemand")
    except AttributeError:
        mod.Zone_Power_Withdrawals.append("ShiftDemand")

def load_inputs(mod, switch_data, inputs_dir):
    # 原有的数据加载逻辑保持不变
    switch_data.load_aug(
        optional=True,
        filename=os.path.join(inputs_dir, "dr_data.csv"),
        param=(mod.dr_shift_down_limit, mod.dr_shift_up_limit),
    )
    # 加载新的参数数据
    switch_data.load_aug(
        optional=True,
        filename=os.path.join(inputs_dir, "dr_response_recovery_data.csv"),
        param=(mod.response_time, mod.recovery_time),
        index=mod.LOAD_ZONES * mod.TIMEPOINTS
    )