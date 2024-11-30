import os
from pyomo.environ import *
from switch_model.utilities import unique_list

"""
This module allows users to specify that hydrogen should be produced and
exported each day. It should be used with
switch_model.energy_sources.hydrogen.production (or similar), which allows
production of hydrogen.

This requires an input file called hydrogen_export.csv that contains two
columns, `date` and `export_hydrogen`. The `date` column should identify the
date (if provided in a tp_dates.csv file) or timeseries when hydrogen will be
exported. The `export_hydrogen` column should show the total amount of hydrogen
to export for non-power-sector uses (in kg) on that date.

This module rewrites the `Hydrogen_Conservation_of_Mass_Daily` constraint
defined in switch_model.energy_sources.hydrogen.production, so it is not
compatible with other modules that also re-write that constraint (e.g.,
study_modules.steam_test)
"""


def define_components(m):

    # Set the dimensionality of the DATES index so we can read export_hydrogen
    # successfully (should not be needed in Switch 2.0.10 or later)
    m.DATES._dimen = m.TIMESERIES.dimen

    # define the amount of hydrogen that must be produced and exported each day
    m.export_hydrogen = Param(
        m.LOAD_ZONES, m.DATES, within=NonNegativeReals, default=0.0
    )

    # replace the hydrogen conservation of mass constraint with one that
    # includes exported hydrogen
    m.del_component(m.Hydrogen_Conservation_of_Mass_Daily)

    @m.Constraint(m.LOAD_ZONES, m.DATES)
    def Hydrogen_Conservation_of_Mass_Daily_Export(m, z, d):
        daily = (
            # daily net removal of compressed hydrogen
            m.StoreLiquidHydrogenKg[z, d]
            + m.export_hydrogen[z, d]
            - m.WithdrawLiquidHydrogenKg[z, d]
        )
        hourly = sum(
            # hourly net creation of compressed hydrogen
            m.ts_duration_of_tp[m.tp_ts[tp]]
            * (m.ProduceHydrogenKgPerHour[z, tp] - m.ConsumeHydrogenKgPerHour[z, tp])
            for tp in m.TPS_IN_DATE[d]
        )
        return daily == hourly

def load_inputs(m, switch_data, inputs_dir):
    """
    Import hydrogen export data from a .csv file.
    """
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, "hydrogen_export.csv"),
        param=(m.export_hydrogen,),
        optional=True,
    )
