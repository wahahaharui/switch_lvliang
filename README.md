1. The raw data is in the input file, and the modified data is in the input_data.
   In input_data, we only add the data information of coal-fired units, and keep the wind power installed data in the original data, but because the wind power installed in the original data is small, can not meet the load demand, so there can be no limits on carbon emissions.
   The results of the run are written to the outputs_add_outside folder.
   The solver used by the model is Gurobi
2. Update11.30 : The `simple_industry_2.py` module has been added to model demand response on the industrial side. The corresponding input data folder is named "inputs_data_add_industry_response", and the output folder is "outputs_industry_2".
3. Update0110 ：

   The latest version of the industrial demand response module is **simple_industry_3.py**.

① Baseline scenario:
The corresponding input data is inputs_data_add_wind_PV.
Comment out the switch_model.policies.carbon_policies module in modules.txt.
Enter the following command line:
switch solve --verbose --stream-solver --sorted-output --inputs-dir inputs_data_add_wind_PV --outputs-dir outputs_base_add_wind_PV --solver cplex --full-traceback --retrieve-cplex-mip-duals

② Baseline scenario + carbon emission constraint
The corresponding input data is inputs_data_add_wind_PV.
Add the switch_model.policies.carbon_policies module to modules.txt.
Enter the following command line:
switch solve --verbose --stream-solver --sorted-output --inputs-dir inputs_data_add_wind_PV --outputs-dir outputs_base_add_wind_PV --solver cplex --full-traceback --retrieve-cplex-mip-duals

③ Baseline scenario + carbon emission constraint + hydrogen
The corresponding input data is inputs_data_add_hydrogen.
Enter the following command line:
switch solve --verbose --stream-solver --sorted-output --inputs-dir inputs_data_add_hydrogen --outputs-dir outputs_base_add_hydrogen --solver cplex --full-traceback --retrieve-cplex-mip-duals

④ Baseline scenario + carbon emission constraint + hydrogen + industrial demand response
The corresponding input data is inputs_data_add_industry_response.
Enter the following command line:
switch solve --verbose --stream-solver --sorted-output --inputs-dir inputs_data_add_industry_response --outputs-dir outputs_industry_3 --solver gurobi --full-traceback
