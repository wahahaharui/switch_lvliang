import os
from pyomo.environ import *
from switch_model.utilities import unique_list

mmbtu_per_mwh = 3.412
# TODO: account for duration of timepoints when converting MW to MWh to MMBtu


def define_arguments(argparser):
    argparser.add_argument(
        "--no-cogen",
        default=False,
        action="store_true",
        help="Do not allow steam to be produced by thermal power plants "
        "(produce all steam directly instead).",
    )


def define_components(m):

    # create steam demand in every timepoint in every zone
    # (for now we assume it's flat and equal to 30% of electricity demand)
    m.steam_demand_avg = Param(
        m.LOAD_ZONES,
        rule=lambda m, z: sum(
            0.0 * m.zone_demand_mw[z, tp] * m.tp_weight[tp] for tp in m.TIMEPOINTS
        )
        / sum(m.tp_weight[tp] for tp in m.TIMEPOINTS),
    )
    m.zone_steam_demand = Param(
        m.LOAD_ZONES, m.TIMEPOINTS, rule=lambda m, z, tp: m.steam_demand_avg[z]
    )
    m.add_demand("steam", m.zone_steam_demand)
    
    # allow burning any fuel directly to produce steam
    m.ZoneDirectSteamByFuel = Var(m.ZONE_FUELS, m.TIMEPOINTS, within=NonNegativeReals)

    # don't allow use of Uranium to produce steam directly (special case)
    m.No_Uranium_For_Steam = Constraint(
        m.LOAD_ZONES,
        m.TIMEPOINTS,
        rule=lambda m, z, tp: (
            m.ZoneDirectSteamByFuel[z, "Uranium", tp] == 0
            if (z, "Uranium") in m.ZONE_FUELS
            else Constraint.Skip
        ),
    )

    # set of all fuels available in each zone
    m.FUELS_IN_ZONE = Set(
        m.LOAD_ZONES,
        initialize=lambda m, z: unique_list(_f for (_z, _f) in m.ZONE_FUELS if _z == z),
    )
    
    # total steam production in each zone in each timepoint
    m.ZoneDirectSteamTotal = Expression(
        m.LOAD_ZONES,
        m.TIMEPOINTS,
        rule=lambda m, z, tp: sum(
            m.ZoneDirectSteamByFuel[z, f, tp] for f in m.FUELS_IN_ZONE[z]
        ),
    )
    m.add_supply("steam", m.ZoneDirectSteamTotal)
    
    # Add the fuel used for direct steam production to the total used in each
    # market and to the daily hydrogen balance (replacing the original
    # constraints(!)). This will also add the cost of that fuel to the model.
    # TODO: add code to switch_model.energy_sources.fuel_costs.markets and
    # switch_mdoel.energy_sources.hydrogen.production to generalize this
    def Enforce_Fuel_Consumption_rule(m, rfm, p):
        generator_fuel = sum(
            m.GenFuelUseRate[g, t, m.rfm_fuel[rfm]] * m.tp_weight_in_year[t]
            for g in m.GENS_FOR_RFM_PERIOD[rfm, p]
            for t in m.TPS_IN_PERIOD[p]
        )
        steam_fuel = sum(
            # convert steam production (MW) to MMBtu, assuming 100% efficiency
            m.ZoneDirectSteamByFuel[z, m.rfm_fuel[rfm], t]
            * mmbtu_per_mwh
            * m.tp_weight_in_year[t]
            for z in m.ZONES_IN_RFM[rfm]
            for t in m.TPS_IN_PERIOD[p]
        )

        return m.FuelConsumptionInMarket[rfm, p] == generator_fuel + steam_fuel
    
    del m.Enforce_Fuel_Consumption
    del m.Enforce_Fuel_Consumption_index
    m.Enforce_Fuel_Consumption = Constraint(
        m.REGIONAL_FUEL_MARKETS, m.PERIODS, rule=Enforce_Fuel_Consumption_rule
    )

    if hasattr(m, "hydrogen_fuel_name"):
        # using hydrogen production module; force production to cover any
        # hydrogen used for direct steam production or export

        # Set the dimensionality of the DATES index so we can read export_hydrogen
        # successfully (should not be needed in Switch 2.0.10 or later)
        m.DATES._dimen = m.TIMESERIES.dimen
        m.export_hydrogen = Param(
            m.LOAD_ZONES, m.DATES, within=NonNegativeReals, default=0.0
        )

        # replace the hydrogen conservation of mass constraint with one that
        # includes hydrogen used for steam or export
        del m.Hydrogen_Conservation_of_Mass_Daily

        @m.Constraint(m.LOAD_ZONES, m.DATES)
        def Hydrogen_Conservation_of_Mass_Daily(m, z, d):
            daily = (
                # daily net removal of compressed hydrogen
                m.StoreLiquidHydrogenKg[z, d]
                + m.export_hydrogen[z, d]
                - m.WithdrawLiquidHydrogenKg[z, d]
            )
            hourly = sum(
                # hourly net creation of compressed hydrogen
                m.ts_duration_of_tp[m.tp_ts[tp]]
                * (
                    m.ProduceHydrogenKgPerHour[z, tp]
                    - m.ConsumeHydrogenKgPerHour[z, tp]
                    - (
                        (
                            m.ZoneDirectSteamByFuel[z, m.hydrogen_fuel_name, tp]
                            * mmbtu_per_mwh
                            / m.hydrogen_mmbtu_per_kg
                        )
                        if (z, value(m.hydrogen_fuel_name), tp)
                        in m.ZoneDirectSteamByFuel
                        else 0.0
                    )
                )
                for tp in m.TPS_IN_DATE[d]
            )
            return daily == hourly

    # TODO: require construction of direct boilers, probably fuel-specific

    # Produce steam from thermal generator waste heat
    if not m.options.no_cogen:
        # amount of steam produced by each generator in each timepoint (MW)
        m.CogenSteam = Var(m.FUEL_BASED_GEN_TPS, within=NonNegativeReals)

        # don't produce more steam than the waste heat allows (currently assumed
        # 100% efficient)
        def rule(m, g, tp):
            # heat input, converted from MMBtu to MW
            heat_input = (
                sum(m.GenFuelUseRate[g, tp, f] for f in m.FUELS_FOR_GEN[g])
                / mmbtu_per_mwh
            )
            # waste heat
            waste_heat = heat_input - m.DispatchGen[g, tp]
            return m.CogenSteam[g, tp] <= waste_heat

        m.CogenSteam_Upper_Limit = Constraint(m.FUEL_BASED_GEN_TPS, rule=rule)

        # Identify all generators that could produce steam in each zone in each
        # period, then use that to calculate total cogen steam production in each
        # zone during each timepoint.
        def rule(m, z, p):
            try:
                d = m.FUEL_BASED_GENS_IN_ZONE_PERIOD_dict
            except AttributeError:
                d = m.FUEL_BASED_GENS_IN_ZONE_PERIOD_dict = {
                    (_z, _p): [] for _z in m.LOAD_ZONES for _p in m.PERIODS
                }
                # tabulate all fuel-powered gens active in each zone in each period
                # (in theory we could just accept m and return d the first time through,
                # but that doesn't actually work)
                for _g in m.FUEL_BASED_GENS:
                    for _p in m.PERIODS_FOR_GEN[_g]:
                        d[m.gen_load_zone[_g], _p].append(_g)
            return d.pop((z, p))

        m.FUEL_BASED_GENS_IN_ZONE_PERIOD = Set(
            m.LOAD_ZONES, m.PERIODS, initialize=rule, dimen=1
        )

        m.ZoneCogenSteam = Expression(
            m.LOAD_ZONES,
            m.TIMEPOINTS,
            rule=lambda m, z, tp: sum(
                m.CogenSteam[g, tp]
                for g in m.FUEL_BASED_GENS_IN_ZONE_PERIOD[z, m.tp_period[tp]]
            ),
        )
        m.add_supply("steam", m.ZoneCogenSteam)

def load_inputs(m, switch_data, inputs_dir):
    """
    Import hydrogen export data from a .csv file.
    """
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, "hydrogen_export.csv"),
        param=(m.export_hydrogen,),
        optional=True,
    )
