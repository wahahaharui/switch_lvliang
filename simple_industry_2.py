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

    mod.ShiftDemand = Var(
        mod.LOAD_ZONES,
        mod.TIMEPOINTS,
        within=Reals,
        bounds=lambda m, z, t: (
            (-1.0) * m.dr_shift_down_limit[z, t],
            m.dr_shift_up_limit[z, t],
        ),
    )

    # Define a demand recovery variable, used for gradually increasing the load.
    mod.RecoveryDemand = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals)

    # Define an absolute value constraint.
    mod.shift_demand_abs = Var(mod.LOAD_ZONES, mod.TIMEPOINTS, within=NonNegativeReals)

    def shift_demand_abs_rule1(m, z, t):
        return m.shift_demand_abs[z, t] >= m.ShiftDemand[z, t]

    def shift_demand_abs_rule2(m, z, t):
        return m.shift_demand_abs[z, t] >= -m.ShiftDemand[z, t]

    mod.Shift_Demand_Abs_Constraint1 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule1)
    mod.Shift_Demand_Abs_Constraint2 = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=shift_demand_abs_rule2)

    # Define a recovery process constraint, assuming that after demand response, the load recovers to its original level in a linear manner.
    def recovery_demand_rule(m, z, t):
        if t > 1:
            return (
                m.RecoveryDemand[z, t]
                == m.RecoveryDemand[z, t - 1]
                + (m.zone_demand_mw[z, t] - m.ShiftDemand[z, t - 1])
                / m.recovery_time[z, t]
            )
        else:
            return Constraint.Feasible

    mod.Recovery_Demand_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=recovery_demand_rule)

    # Bind the activation variable with the logic of demand adjustment.
    def is_dr_active_rule(m, z, t):
        return m.is_DR_active[z, t] >= (m.shift_demand_abs[z, t] / m.dr_shift_up_limit[z, t]) - 1e-6

    mod.Is_DR_Active_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=is_dr_active_rule)

    # Two-response interval time constraint.
    def dr_min_interval_rule(m, z, t):
        # Ensure that t - i is within the valid time range.
        # Include the preparation time, increasing the total duration interval to 5 hours/6 hours.
        valid_indices = [t - i for i in range(1, 7) if t - i >= 1]
        if valid_indices:
            # Ensure that there is no more than 1 activation in the recent 5/6 hours.
            return sum(m.is_DR_active[z, ti] for ti in valid_indices) <= 1
        else:
            # If there is no valid index, return a constraint that is always satisfied.
            return Constraint.Feasible

    mod.DR_Min_Interval_Constraint = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=dr_min_interval_rule)

    def enforce_preparation_time_rule(m, z, t):
        if t <= m.response_time[z, t]:
            # If the current time point is less than or equal to the preparation time, then demand response cannot be activated.
            return m.is_DR_active[z, t] == 0
        else:
            return Constraint.Feasible

    mod.Enforce_Preparation_Time = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=enforce_preparation_time_rule)

    # Prohibit triggering demand response near the time points requiring recovery.
    def prevent_dr_in_last_periods_rule(m, z, t):
        if t > len(m.TIMEPOINTS) - m.recovery_time[z, t]:
            return m.is_DR_active[z, t] == 0
        else:
            return Constraint.Feasible

    mod.Prevent_DR_In_Last_Periods = Constraint(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=prevent_dr_in_last_periods_rule)
    
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
        rule=lambda m, z, ts: sum(m.ShiftDemand[z, t] for t in m.TPS_IN_TS[ts]) == 0.0,
    )

    try:
        mod.Distributed_Power_Withdrawals.append("ShiftDemand")
    except AttributeError:
        mod.Zone_Power_Withdrawals.append("ShiftDemand")

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