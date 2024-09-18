import types, os
import pyomo.environ as pyo
from switch_model.reporting import write_table, make_iterable

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
    # m.commodities_dict will be a dictionary like
    # {
    #     commodity: {"supply": [expr1, expr2], "demand": [expr3, expr4]},
    #     commodity2: {}
    # }
    # It is built incrementally by add_supply() and add_demand(). The inner
    # dictionary shows a list of names of all expressions that have been
    # registered for the particular commodity. Switch will require that the sum
    # of the supply expressions equals the sum of the demand expressions for
    # each step in the index(es) of these components. We currently require that
    # all components that define supply or demand for the same commodity must
    # use the same index set. We use names instead of objects because Pyomo
    # uses different objects in the model definition and construction stages.
    m.commodities_dict = {}

    # attach the add_* functions as methods of the model object
    for func in (
        add_supply,
        add_demand,
        add_timepoint_cost,
        add_annual_cost,
    ):
        setattr(m, func.__name__, types.MethodType(func, m))


def define_dynamic_components(m):
    """
    Create constraint to balance supply and demand of each commodity during each
    index step. (Constraint is constructed after other components, so it can
    access the final index set for each supply and demand.)
    """
    # define a constraint list that can use any indexing
    # (see https://groups.google.com/g/pyomo-forum/c/5DgnivI1JRY/m/G3XpOxAkBQAJ)
    m.CommodityBalance = pyo.Constraint(pyo.Any)

    # add all components to this (late in the model construction process)
    def rule(m):
        for commodity in m.commodities_dict:
            # verify that all the components use the same indexing
            check_commodity_index_consistency(m, commodity)
            # define balances for each step for each commodity
            for keys in commodity_index(m, commodity):
                m.CommodityBalance[commodity, keys] = commodity_sum(
                    m, commodity, "supply", keys
                ) == commodity_sum(m, commodity, "demand", keys)

    Construct_CommodityBalance = pyo.BuildAction(rule=rule)


def post_solve(m, outdir):
    # create <commodity>_balance.csv tables showing step by step supply and
    # demand for each commodity (we can't aggregate to higher levels because
    # we don't know whether the indexes are timepoints, timeseries, etc.)
    for commodity, comm_data in m.commodities_dict.items():
        cols = comm_data["supply"] + comm_data["demand"]
        index = commodity_index(m, commodity)
        write_table(
            m,
            index,
            output_file=os.path.join(outdir, f"{commodity}_balance.csv"),
            headings=[f"INDEX_{n+1}" for n in range(index.dimen)] + cols,
            values=lambda m, keys: list(keys) + [getattr(m, c)[keys] for c in cols],
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
    m.commodities_dict.setdefault(commodity, {}).setdefault(supply_demand, []).append(
        expr.name
    )


def check_commodity_index_consistency(m, commodity):
    # check that all expressions used for supply or demand for this commodity
    # use the same indexing,
    steps = None
    for supply_demand, exprs in m.commodities_dict[commodity].items():
        for expr_name in exprs:
            expr = getattr(m, expr_name)
            if steps is None:
                steps = set(expr)  # expr is dict-like, so this gets the keys
                first_expr = expr
            elif set(expr) != steps:
                raise ValueError(
                    f"For commodity '{commodity}', expression '{expr.name}' "
                    f"is indexed differently than expression '{first_expr.name}."
                )


def commodity_index(m, commodity):
    # return index keys for the specified commodity; this uses the first
    # supply or demand specified for this commodity, so
    # check_commodity_index_consistency should have been run previously
    steps = None
    for supply_demand, exprs in m.commodities_dict[commodity].items():
        for expr_name in exprs:
            expr = getattr(m, expr_name)
            steps = set(expr)  # expr is dict-like, so this gets the keys

    return steps


def commodity_sum(m, commodity, supply_demand, keys):
    """
    Return total supply or demand for this commodity at the step indicated by
    `keys`. We have to refer to expressions by name instead of reference because
    they are not the same object as existed when the model was defined.
    """
    return sum(
        getattr(m, expr)[keys]
        # note: we use .get() to produce an empty sum if supplies or demands have
        # not been defined
        for expr in m.commodities_dict[commodity].get(supply_demand, [])
    )
