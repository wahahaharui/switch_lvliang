import os
from pyomo.environ import *

dependencies = "switch_model.timescales", "switch_model.balancing.load_zones"
optional_dependencies = "switch_model.transmission.local_td"

def define_components(mod):
    # Retain the original parameter and variable definitions.
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

    mod.response_time = Param(
        mod.LOAD_ZONES, mod.TIMEPOINTS, default=1.0, within=NonNegativeReals
    )
    mod.recovery_time = Param(
        mod.LOAD_ZONES, mod.TIMEPOINTS, default=2.0, within=NonNegativeReals
    )

    # To define an activation variable for demand response, where 1 indicates that demand response is activated and 0 indicates that demand response is not activated
    mod.is_DR_active = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=Binary)

    # define ShiftDemandUp & ShiftDemandDown to simplify the code
    mod.ShiftDemandUp = Var(
        mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals,
        bounds=lambda m, z, t: (0, m.dr_shift_up_limit[z, t])
    )
    mod.ShiftDemandDown = Var(
        mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals,
        bounds=lambda m, z, t: (0, m.dr_shift_down_limit[z, t])
    )

    # define ShiftDemand as the difference between the two
    mod.ShiftDemand = Expression(
        mod.LOAD_ZONES, mod.TIMEPOINTS,
        rule=lambda m, z, t: m.ShiftDemandUp[z, t] - m.ShiftDemandDown[z, t]
    )

    def dr_six_hour_limit_rule_up(m, z, ts):
        six_hour_timepoints = [
            t for t in m.TPS_IN_TS[ts] if t in m.TIMEPOINTS
        ]
        return sum(m.ShiftDemandUp[z, t] for t in six_hour_timepoints) <= m.dr_shift_up_limit[z, six_hour_timepoints[0]]

    def dr_six_hour_limit_rule_down(m, z, ts):
        six_hour_timepoints = [
            t for t in m.TPS_IN_TS[ts] if t in m.TIMEPOINTS
        ]
        return sum(m.ShiftDemandDown[z, t] for t in six_hour_timepoints) <= m.dr_shift_down_limit[z, six_hour_timepoints[0]]

    mod.DR_Six_Hour_Limit_Constraint_Up = Constraint(mod.LOAD_ZONES, mod.TIMESERIES, rule=dr_six_hour_limit_rule_up)
    mod.DR_Six_Hour_Limit_Constraint_Down = Constraint(mod.LOAD_ZONES, mod.TIMESERIES, rule=dr_six_hour_limit_rule_down)

    # Define a demand recovery variable, used for gradually increasing the load.
    mod.RecoveryDemand = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=Reals)

    # Define an absolute value constraint.
    mod.shift_demand_abs = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals)

    def shift_demand_abs_rule1(m, z, t):
        return m.shift_demand_abs[z, t] >= m.ShiftDemand[z, t]

    def shift_demand_abs_rule2(m, z, t):
        return m.shift_demand_abs[z, t] >= -m.ShiftDemand[z, t]

    mod.Shift_Demand_Abs_Constraint1 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule1)
    mod.Shift_Demand_Abs_Constraint2 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule2)

    # make sure ShiftDemandUp & ShiftDemandDown influenced by is_DR_active
    mod.Enforce_ShiftDemandUp_When_Active = Constraint(
        mod.LOAD_ZONES, mod.TIMEPOINTS,
        rule=lambda m, z, t: m.ShiftDemandUp[z, t] <= m.is_DR_active[z, t] * m.dr_shift_up_limit[z, t]
    )
    mod.Enforce_ShiftDemandDown_When_Active = Constraint(
        mod.LOAD_ZONES, mod.TIMEPOINTS,
        rule=lambda m, z, t: m.ShiftDemandDown[z, t] <= m.is_DR_active[z, t] * m.dr_shift_down_limit[z, t]
    )

    # Define a recovery process constraint, assuming that after demand response, the load recovers to its original level in a linear manner.
    def recovery_demand_rule(m, z, t):
        # calculate the earliest hour that could have a ShiftDemand value that
        # is still in recovery phase now
        n_steps_back = int(m.recovery_time[z, t] / m.tp_duration_hrs[t])
        return (
            m.RecoveryDemand[z, t]
            ==
            # sum the correct fraction of any events within the lookback window
            sum(
                # ShiftDemand during prior timepoint (i steps back)
                m.ShiftDemand[z, m.TPS_IN_TS[m.tp_ts[t]].prevw(t, i)]
                # fraction that should still be active in current timepoint (i steps later)
                * (1 - i * m.tp_duration_hrs[i] / m.recovery_time[z, t])
                for i in range(n_steps_back, 0, -1)
            )
        )

    mod.Recovery_Demand_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=recovery_demand_rule)

    # Bind the activation variable with the logic of demand adjustment.
    def is_dr_active_rule(m, z, t):
        return m.is_DR_active[z, t] >= (m.shift_demand_abs[z, t] / m.dr_shift_up_limit[z, t]) - 1e-6

    mod.Is_DR_Active_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=is_dr_active_rule)

    # Two-response interval time constraint.
    def dr_min_interval_rule(m, z, t):
        # Include the preparation time, increasing the total duration interval to 6 hours.
        valid_indices = [m.TPS_IN_TS[m.tp_ts[t]].prevw(t, i) for i in range(1, 7)]
        if valid_indices:
            # Ensure that there is no more than 1 activation in the recent 6 hours.
            return sum(m.is_DR_active[z, ti] for ti in valid_indices) <= 1
        else:
            # If there is no valid index, return a constraint that is always satisfied.
            return Constraint.Feasible

    mod.DR_Min_Interval_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_min_interval_rule)

    # Ensure that when demand response is not activated, there is no load adjustment behavior.
    def enforce_shift_demand_zero_when_inactive_rule_upper(m, z, t):
        # Ensure that ShiftDemand <= is_DR_active * dr_shift_up_limit
        return m.ShiftDemand[z, t] <= m.is_DR_active[z, t] * m.dr_shift_up_limit[z, t]

    def enforce_shift_demand_zero_when_inactive_rule_lower(m, z, t):
        # Ensure that ShiftDemand >= -is_DR_active * dr_shift_down_limit
        return m.ShiftDemand[z, t] >= -m.is_DR_active[z, t] * m.dr_shift_down_limit[z, t]

    # Add two constraints separately.
    mod.Enforce_ShiftDemand_Zero_When_Inactive_Upper = Constraint(
        mod.LOAD_ZONES, mod.TIMEPOINTS, rule=enforce_shift_demand_zero_when_inactive_rule_upper
    )
    mod.Enforce_ShiftDemand_Zero_When_Inactive_Lower = Constraint(
        mod.LOAD_ZONES, mod.TIMEPOINTS, rule=enforce_shift_demand_zero_when_inactive_rule_lower
    )

    # Maintain a constant load transfer within each time step for balancing demand response constraints.
    mod.DR_Shift_Net_Zero = Constraint(
        mod.LOAD_ZONES,
        mod.TIMESERIES,
        rule=lambda m, z, ts: sum(m.ShiftDemand[z, t] + m.RecoveryDemand[z, t] for t in m.TPS_IN_TS[ts]) == 0.0,
    )

    try:
        mod.Distributed_Power_Withdrawals.append("ShiftDemand")
        mod.Distributed_Power_Withdrawals.append("RecoveryDemand")
    except AttributeError:
        mod.Zone_Power_Withdrawals.append("ShiftDemand")
        mod.Zone_Power_Withdrawals.append("RecoveryDemand")

def load_inputs(mod, switch_data, inputs_dir):
    # Keep the original data loading logic unchanged
    switch_data.load_aug(
        optional=True,
        filename=os.path.join(inputs_dir, "dr_data.csv"),
        param=(mod.dr_shift_down_limit, mod.dr_shift_up_limit),
    )
    # Load new parameter data
    switch_data.load_aug(
        optional=True,
        filename=os.path.join(inputs_dir, "dr_response_recovery_data.csv"),
        param=(mod.response_time, mod.recovery_time),
        index=mod.LOAD_ZONES * mod.TIMEPOINTS
    )