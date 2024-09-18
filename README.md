The raw data is in the input file, and the modified data is in the input_data. 
In input_data, we only add the data information of coal-fired units, and keep the wind power installed data in the original data, but because the wind power installed in the original data is small, can not meet the load demand, so there can be no limits on carbon emissions. 
The results of the run are written to the outputs_add_outside folder. 
The solver used by the model is Gurobi


Github Update 2024/09/18

A new folder named inputs_data_add_hydrogen has been added, which includes the hydrogen_supply module. In gen_info, a new H2 unit has been added; it is an electrolyzer unit. Additionally, four retrofit coal-fired units have been defined in gen_retrofits.csv (these were randomly defined as I'm not sure which specific units need retrofitting or if all units should be retrofitted).

The command to run is: switch solve --verbose --stream-solver --sorted-output --inputs-dir inputs_data_add_hydrogen --outputs-dir outputs_add_hydrogen --solver gurobi --full-traceback
