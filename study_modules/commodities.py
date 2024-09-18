import types, os
import pyomo.environ as pyo
from switch_model.reporting import write_table

"""
Manage supply-demand balance for any commodities chosen by the user.

This module adds the following methods to the model:

    m.add_supply("commodity", m.Component)
    m.add_demand("commodity", m.Component)
    m.add_timepoint_cost(m.Component)
    m.add_annual_cost(m.Component)

`m.add_supply()` and `m.add_demand` register the specified model component
(which should be a `Var`, `Expression` or `Param`) as a source or sink for the
specified commodity. Switch will then require that the sum of all supplies
equals the sum of all demands for every step of the index of `m.Component`.
All components that are registered as supplies or demands for the same commodity
must use the same index.

`m.add_timepoint_cost()` and `m.add_annual_cost()` add the specified component
to the total cost of the model. Components passed to `m.add_timepoint_cost()`
must be indexed over m.TIMEPOINTS and show a cost per timepoint. Switch
calculates the weighted sum of these based on `m.tp_weight` for each timepoint,
then discounts it to the model base year and adds it to the objective function.
Components passed to `m.add_annual_cost()` must be indexed over m.PERIODS and
show a cost per year. Switch repeats this as needed to span the whole period and
discounts it to the base year and adds it to the objective function.
"""


def define_components(m):
    # m.CommodityBalance.commodities will be a dictionary like
    # {
    #     commodity: {"supply": [expr1, expr2], "demand": [expr3, expr4]},
    #     commodity2: {}
    # }
    # It is built incrementally by add_supply() and add_demand(). The inner
    # dictionary shows a list of all expressions that have been registered for
    # the particular commodity. Switch will require that the sum of the supply
    # expressions equals the sum of the demand expressions for each step in the
    # index(es) of these components. We currently require that all components
    # that define supply or demand for the same commodity must use the same
    # index set.
    m.CommodityBalance = pyo.Block()
    m.CommodityBalance.commodities = {}

    # attach the add_* functions as methods of the model object
    for func in (
        add_supply,
        add_demand,
        add_timepoint_cost,
        add_annual_cost,
    ):
        setattr(m, func.__name__, types.MethodType(func, m))


def pre_solve(m):
    """
    Create components to balance supply and demand of each commodity, during
    each index step. (Runs after model is constructed, to obtain the
    final index_set() for each supply and demand.)
    """
    for commodity in m.CommodityBalance.commodities:
        setattr(
            m.CommodityBalance,
            "Balance_" + commodity,
            pyo.Constraint(
                commodity_index(m, commodity),
                rule=lambda cb, *keys: commodity_sum(cb, commodity, "supply", keys)
                == commodity_sum(cb, commodity, "demand", keys),
            ),
        )


def post_solve(m, outdir):
    # create <commodity>_balance.csv tables showing step by step supply and
    # demand for each commodity (we can't aggregate to higher levels because
    # we don't know whether the indexes are timepoints, timeseries, etc.)
    for commodity, comm_data in m.CommodityBalance.commodities.items():
        cols = comm_data["supply"] + comm_data["demand"]
        index = getattr(m.CommodityBalance, "Balance_" + commodity).index_set()
        write_table(
            m,
            index,
            output_file=os.path.join(outdir, f"{commodity}_balance.csv"),
            headings=[f"INDEX_{n+1}" for n in range(index.dimen)] + cols,
            values=lambda m, *keys: list(keys) + [getattr(m, c)[keys] for c in cols],
        )


def add_supply(m, commodity, expr):
    add_supply_demand(m, "supply", commodity, expr)


def add_demand(m, commodity, expr):
    add_supply_demand(m, "demand", commodity, expr)


def add_timepoint_cost(m, expression):
    """
    register per-timepoint costs using the standard dynamic list
    """
    m.Cost_Components_Per_TP.append(expression.name)


def add_annual_cost(m, expression):
    """
    register per-year costs using the standard dynamic list
    """
    m.Cost_Components_Per_Period.append(expression.name)


def add_supply_demand(m, supply_demand, commodity, expr):
    """
    Helper function to register a supply or demand of a commodity.
    """
    # Note: we use component names instead of objects, so we can find them again
    # by name after the model is copied to a concrete instance.
    m.CommodityBalance.commodities.setdefault(commodity, {}).setdefault(
        supply_demand, []
    ).append(expr.name)


def commodity_index(m, commodity):
    # check that all expressions used for supply or demand for this commodity
    # use the same indexing, then return those index keys
    steps = None
    for supply_demand, exprs in m.CommodityBalance.commodities[commodity].items():
        for expr_name in exprs:
            expr = getattr(m, expr_name)
            if steps is None:
                steps = set(expr.index_set())
                first_expr = expr
            elif set(expr.index_set()) != steps:
                raise ValueError(
                    f"For commodity '{commodity}', expression '{expr.name}' "
                    f"is indexed differently than expression '{first_expr.name}."
                )
    return steps


def commodity_sum(cb, commodity, supply_demand, keys):
    """
    Return total supply or demand for this commodity at the step indicated by
    `keys`.
    """
    return sum(
        # note: this will be called on the CommodityBalance block, so we have to
        # refer back from there to the underlying model
        getattr(cb.model(), expr)[keys]
        # note: we use .get() to produce an empty sum if supplies or demands have
        # not been defined
        for expr in cb.commodities[commodity].get(supply_demand, [])
    )
