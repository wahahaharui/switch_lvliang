1.The raw data is in the input file, and the modified data is in the input_data.
In input_data, we only add the data information of coal-fired units, and keep the wind power installed data in the original data, but because the wind power installed in the original data is small, can not meet the load demand, so there can be no limits on carbon emissions.
The results of the run are written to the outputs_add_outside folder.
The solver used by the model is Gurobi

2. Update11.30 : The `simple_industry_2.py` module has been added to model demand response on the industrial side. The corresponding input data folder is named "inputs_data_add_industry_response", and the output folder is "outputs_industry_2".
