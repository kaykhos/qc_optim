#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:10:36 2020
@author: Kiran
"""

import sys
import GPyOpt
import numpy as np
import qiskit as qk
import matplotlib.pyplot as plt
sys.path.insert(0, '../core/')
import ansatz as az
import cost as cost
import utilities as ut
import optimisers as op




# ===================
# Defaults
# ===================
pi= np.pi
NB_SHOTS_DEFAULT = 8192
OPTIMIZATION_LEVEL_DEFAULT = 0
TRANSPILER_SEED_DEFAULT = 10
NB_INIT = 100
NB_ITER = 50
CHOOSE_DEVICE = False


# ===================
# Choose a backend using the custom backend manager and generate an instance
# ===================
try:
    bem
except:
    bem = ut.BackendManager()
    
if CHOOSE_DEVICE:
    bem.get_current_status()
    chosen_device = int(input('SELECT IBM DEVICE:'))
    bem.get_backend(chosen_device, inplace=True)
else:
    bem.get_backend(4, inplace=True)
inst = bem.gen_instance_from_current()

# ===================
# Generate ansatz and const functins (will generalize this in next update)
# ===================
anz0 = az.AnsatzFromFunction(az._GHZ_3qubits_6_params_cx0)
anz1 = az.AnsatzFromFunction(az._GHZ_3qubits_6_params_cx1)
anz2 = az.AnsatzFromFunction(az._GHZ_3qubits_6_params_cx2)

cst0 = cost.GHZPauliCost(anz0, inst)
cst1 = cost.GHZPauliCost(anz1, inst)
cst2 = cost.GHZPauliCost(anz2, inst)

# ======================== /
#  Default BO args - consider passing this into an extension of Batch class
# ======================== /
bo_args = ut.gen_default_argsbo(f=lambda x: 0.5, 
                                domain= [(0, 2*np.pi) for i in range(anz0.nb_params)], 
                                nb_init=0,
                                eval_init=False)

# ======================== /
# Init optimiser class
# ======================== /
optim = op.ParallelOptimizer([cst0, cst1, cst2], 
                             GPyOpt.methods.BayesianOptimization, 
                             optimizer_args=bo_args,
                             share_init=False,
                             nb_init=5)

# NO FUCKING CLUE WHY THIS HAPENS???? eval_init=False should return NONE????
print(optim.optim_list[0].X)
print(optim.optim_list[0].Y)


# ========================= /
# But it works:
# ========================= /
Batch = ut.Batch(instance=inst)
optim.gen_init_circuits()
Batch.submit(optim)
Batch.submit(optim.circs_to_exec, 'this_is_a_test_of_naming')
Batch.execute()
results_obj = Batch.result(optim)
other_results_obj = Batch.result('this_is_a_test_of_naming')
optim.init_optimisers(results_obj)

# optimizers now have new init info. 
print(optim.optim_list[0].X)
print(optim.optim_list[0].Y)

optim.next_evaluation_circuits()
Batch.submit(optim)
Batch.execute()
results_obj = Batch.result(optim)
optim.update(results_obj)

# update sucessfull (shared data)
print(optim.optim_list[0].X)
print(optim.optim_list[0].Y)

#%% Everything here is old and broken

# # ======================== /
# #  Init each BO seperately (might put this in Batch class, or extended class)
# # ======================== /
# bo_arg_list, bo_list = [], []
# for cst in multi_cost.cost_list:
#     cost_bo = lambda x: 1-cst(x) 
#     bo_args = ut.gen_default_argsbo(f=cost_bo, domain=DOMAIN_FULL, nb_init=NB_INIT)
#     bo_args.update({'acquisition_weight': 7}) # increase exploration
#     bopt = GPyOpt.methods.BayesianOptimization(**bo_args)
#     bopt.run_optimization(max_iter = 0, eps = 0) 
    
#     # Opt runs on a list of bo args
#     bo_arg_list.append(bo_args)
#     bo_list.append(GPyOpt.methods.BayesianOptimization(**bo_args))
    
 
# # ======================== /
# #  Run opt using the nice efficient class (need to repackage)
# # ======================== /
# for ii in range(NB_ITER):
#     x_new = multi_cost.get_new_param_points(bo_list)
#     y_new = 1 - np.array(multi_cost(x_new))
#     multi_cost.update_bo_inplace(bo_list, x_new, y_new)
#     for bo in bo_list:
#         bo.acquisition.exploration_weight = dynamics_weight(ii)
#     print(ii)

 
# # ======================== /
# #  Print at results
# # ======================== /
# x_opt_pred = []
# for bo in bo_list:
#     bo.run_optimization(max_iter = 0, eps = 0) 
#     (x_seen, y_seen), (x_exp,y_exp) = bo.get_best()
#     #fid_test(x_seen)
#     #fid_test(x_exp)
#     print(bo.model.model)
#     bo.plot_convergence()
#     plt.show()
#     x_opt_pred.append(bo.X[np.argmin(bo.model.predict(bo.X, with_noise=False)[0])])


# # ======================== /
# # Get a baseline to compare to BO and save result
# # ======================== /
# if type(x_sol) != ut.NoneType:
#     baseline_values = multi_cost.shot_noise(x_sol, 10)
# else:
#     baseline_values = None
# bopt_values = multi_cost.shot_noise(x_opt_pred, 10)


# # ======================== /
# # Save BO's in different files
# # ======================== /
# for cst, bo, bl_val, bo_val, bo_args in zip(multi_cost.cost_list,
#                                             bo_list,
#                                             baseline_values,
#                                             bopt_values,
#                                             bo_arg_list):
#     ut.gen_pkl_file(cst, bo, 
#                     baseline_values = bl_val, 
#                     bopt_values = bo_val, 
#                     path = '/home/kiran/Documents/onedrive/Active_Research/QuantumSimulation/BayesianStateOptimizaiton/qc_optim/results_pkl/',
#                     info = 'cx' + str(cst.main_circuit.count_ops()['cx']) + '_',
#                     dict_in = {'bo_args':bo_args,
#                                'x_sol':x_sol})
    
    
