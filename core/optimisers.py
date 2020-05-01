
# list of * contents
__all__ = [
    'Optimiser',
    'BayesianOptim',
]

import numpy as np
import utilities as ut
import copy
import cost
from abc import ABC, abstractmethod
pi = np.pi

class Optimiser(ABC):
    """
    Interface for an Optimiser class. The optimiser must have two methods:
    one that returns a set of quantum circuits and another that takes new 
    data in and updates the internal state of the optimiser. It also has a
    property `prefix` that is used as an ID by the batch class.
    """

    @abstractmethod
    def next_evaluation_circuits(self):
        """ 
        Return the next set of Cost function evaluations, in the form of 
        executable qiskit quantum circuits
        """
        raise NotImplementedError

    @abstractmethod
    def update(self,results_obj):
        """ Process a new set of data in the form of a results object """
        raise NotImplementedError

    @property
    def prefix(self):
        return self._prefix

class BayesianOptim(Optimiser):
    """
    """

    def __init__(
        self,
        cost_obj,
        nb_init='max',
        init_jobs=1,
        verbose=False,
        **bo_args,
        ):
        """ 
        Parameters
        ----------
        cost_obj : Cost object
            These define the parallelised BO tasks being performed.
        nb_init : int or keyword 'max', default 'max'
            (BO) Sets the number of initial data points to feed into the BO 
            before starting iteration rounds. If set to 'max' it will 
            generate the maximum number of initial points such that it 
            submits `init_jobs` worth of circuits to a qiskit backend.
        init_jobs : int, default 1
            (BO) The number of qiskit jobs to use to generate initial data. 
            (Most real device backends accept up to 900 circuits in one job.)
        verbose : bool, optional
            Set level of output of the object
        bo_args : dict
            Additional args to pass to the GPyOpt BayesianOptimization init
        """

        # make (hopefully) unique id
        import time
        self._prefix = str(hash(time.time()))[:16]

        # unpack other args
        self.cost_obj = cost_obj
        self.nb_init = nb_init
        self.init_jobs = init_jobs
        self.verbose = verbose
        self.bo_args = bo_args

        # stop the BO trying to make function calls when created
        self.bo_args['initial_design_numdata'] = 0

        # still needs initial data
        self._initialised = False

    def next_evaluation_circuits(self):
        """ 
        Get the next set of evaluation circuits.

        Returns
        -------
        bound_circuits : list of executable qiskit circuits
            This is the set of circuits that need to be evaluated in order
            to update the internal state of the optimiser
        """
        # save where the evaluations were requested
        self._last_x = self._next_evaluation_points()

        return self._bind_circuits(self._last_x)

    def update(self,results_obj,experiment_name=''):
        """ 
        Update the internal state of the underlying GPyOpt BO object with
        new data. If this object has not previously recieved initialisation
        data this call spawns the GPyOpt BO object.

        Parameters
        ----------
        results_obj : qiskit results object
            This contains the outcomes of the qiskit experiment or 
            simulation and is used to evaluate the cost object at the 
            requested points
        experiment_name : optional string
            Passed to the cost object's evaluation function in order to 
            specify which qiskit experiment contains the relevant data
        """
        # evaluate cost values
        y_new = np.zeros((self._last_x.shape[0],1))
        for idx in range(y_new.size):
            y_new[idx] = self.cost_obj.meas_func(results_obj,experiment_name=experiment_name)
           
        # add data to internal GPyOpt BO object
        if not self._initialised:
            self._BO = GPyOpt.methods.BayesianOptimization(lambda x: None, # blank cost function
                                                           X=self._last_x, 
                                                           Y=y_new, 
                                                           **self.bo_args)
            self._initialised = True
        else:
            self._BO.X = np.vstack((self._BO.X,self._last_x))
            self._BO.Y = np.vstack((self._BO.Y,y_new))

    def _next_evaluation_points(self):
        """ 
        Returns the next set of points to be evaluated for in the form
        specified by the underlying GPyOpt BO class:
            x : 2d array where with one row for each point to be evaluated

        If the BO class has not yet recieved initialisation data this is
        a number of random points (set by __init__) distributed uniformly
        over the domain of the BO, else it is yielded by the GPyOpt BO obj.
        """

        if not self._initialised:
            # if 'max' initial points work out number of evaluations 
            _nb_init = self.nb_init
            if _nb_init=='max':
                _nb_init = self.init_jobs*900//len(self.cost_obj.meas_circuits)
            # get random points over domain
            return self._get_random_points_in_domain(size=_nb_init)
        else:
            # get next evaluation from BO
            return self.BO._compute_next_evaluations()

    def _get_random_points_in_domain(self,size=1):
        """ 
        Generate a requested number of random points distributed uniformly
        over the domain of the BO parameters.
        """
        for idx,dirn in enumerate(self.bo_args['domain']):
            assert int(dirn['name'])==idx, 'BO domain not being returned in correct order.'
            assert dirn['type']=='continuous', 'BO domain is not continuous, this is not supported.'

            dirn_min = dirn['domain'][0]
            dirn_diff = dirn['domain'][1]-dirn_min
            if idx==0:
                rand_points = dirn_min + dirn_diff*np.array([np.random.random(size=size)]).T
            else:
                _next = dirn_min + dirn_diff*np.array([np.random.random(size=size)]).T
                rand_points = np.hstack((rand_points,_next))

        return rand_points

    def _bind_circuits(self,params_values):
        """
        Binds parameter values, getting the transpiled measurment circuits
        and the qiskit parameter objects from `self.cost_obj`
        """
        if np.ndim(params_values)==1:
            params_values = [params_values]

        # package and bind circuits
        bound_circs = []
        for pidx,p in enumerate(params_values):
            for cc in self.cost_obj.meas_circuits:
                tmp = cc.bind_parameters(dict(zip(self.cost_obj.qk_vars, p)))
                tmp.name = str(pidx) + tmp.name
                bound_circs.append(tmp)
             
        return bound_circs

class BayesianOptimParallel(Optimiser):
    """
    """

    def __init__(
        self,
        cost_objs,
        info_sharing_mode='shared',
        nb_init='max',
        init_jobs=1,
        verbose=False,
        **bo_args,
        ):
        """ 
        Parameters
        ----------
        cost_objs : list of Cost objects
            These define the parallelised BO tasks being performed.
        info_sharing_mode : {'independent','shared','random','left','right'}
            (BO) This controls the evaluation sharing of the BO 
            instances, cases:
                'independent' : The BO do not share data, each only recieves 
                    its own evaluations.
                'shared' :  Each BO obj gains access to evaluations of all 
                    of the others. 
                'random1' : The BO do not get the evaluations others have 
                    requested, but in addition to their own they get an 
                    equivalent number of randomly chosen parameter points 
                'random2' : The BO do not get the evaluations others have 
                    requested, but in addition to their own they get an 
                    equivalent number of randomly chosen parameter points. 
                    These points are not chosen fully at random, but instead 
                    if x1 and x2 are BO[1] and BO[2]'s chosen evaluations 
                    respectively then BO[1] get an additional point y2 that 
                    is |x2-x1| away from x1 but in a random direction, 
                    similar for BO[2], etc.
                'left', 'right' : Implement information sharing but in a 
                    directional way, so that (using 'left' as an example) 
                    BO[1] gets its evaluation as well as BO[0]; BO[2] gets 
                    its point as well as BO[1] and BO[0], etc. To ensure all 
                    BO's get an equal number of evaluations this is padded 
                    with random points. These points are not chosen fully at 
                    random, they are chosen in the same way as 'random2' 
                    described above.
        nb_init : int or keyword 'max', default 'max'
            (BO) Sets the number of initial data points to feed into the BO 
            before starting iteration rounds. If set to 'max' it will 
            generate the maximum number of initial points such that it 
            submits `init_jobs` worth of circuits to a qiskit backend.
        init_jobs : int, default 1
            (BO) The number of qiskit jobs to use to generate initial data. 
            (Most real device backends accept up to 900 circuits in one job.)
        verbose : bool, optional
            Set level of output of the object
        bo_args : dict
            Additional args to pass to the GPyOpt BayesianOptimization init
        """
        
        # make unique id
        import time
        self._prefix = str(hash(time.time()))[:16]

        # run checks and cleanup on cost objs
        _cost_objs = self._enforce_cost_objs_consistency(cost_objs)

        # unpack other args
        self.cost_obj = cost_obj
        self.nb_init = nb_init
        self.init_jobs = init_jobs
        self.verbose = verbose
        self.bo_args = bo_args

        # spawn individual BOpt objs
        self.BOpts = [ BayesianOptim(c,**bo_args) for c in _cost_objs ]

        # still needs initial data
        self._initialised = False

    def _enforce_cost_objs_consistency(self,cost_objs):
        """
        Carry out some error checking on the Cost objs passed to the class
        constructor. Fix small fixable errors and crash for bigger errors.
        
        Parameters
        ----------
        cost_objs : list of cost objs 
            The cost objs passed to __init__

        Returns
        -------
        new_cost_objs : list of cost objs
            Possibly slightly altered list of cost objs
        """

        # TODO: Only makes sense to do this if the cost objs are based on 
        # the WeightedPauliOps class. Should check that and skip otherwise

        new_cost_objs = []
        for idx,op in enumerate(cost_objs):

            if idx>0:
                assert op.num_qubits==num_qubits, ("Cost operators passed to"
                    +" BOptParallel do not all have the same number of qubits.")

                if not len(op.paulis)==len(test_pauli_set):
                    # the new qubit op has a different number of Paulis than the previous
                    new_pauli_set = set([ p[1] for p in op.paulis ])
                    if len(op.paulis)>len(test_pauli_set):
                        # the new operator set has more paulis the previous
                        missing_paulis = list(new_pauli_set - test_pauli_set)
                        paulis_to_add = [ [op.atol*10,p] for p in missing_paulis ]
                        wpo_to_add = wpo(paulis_to_add)
                        # iterate over previous qubit ops and add new paulis
                        for prev_op in qubit_ops:
                            prev_op.add(wpo_to_add)
                        # save new reference pauli set
                        test_pauli_set = new_pauli_set
                    else:
                        # the new operator set has less paulis than the previous
                        missing_paulis = list(test_pauli_set - new_pauli_set)
                        paulis_to_add = [ [op.atol*10,p] for p in missing_paulis ]
                        wpo_to_add = wpo(paulis_to_add)
                        # add new paulis to current qubit op
                        op.add(wpo_to_add)
            else:
                test_pauli_set = set([ p[1] for p in op.paulis ])
                num_qubits = op.num_qubits

            new_cost_objs.append(op)

        return new_cost_objs


class ParallelOptimizer(Optimiser):
    """ 
    Class that wraps a set of quantum optimisation tasks. It separates 
    out the cost function evaluation requests from the updating of the 
    internal state of the optimisers to allow aggregation of quantum 
    jobs. It also supports different information sharing approaches 
    between the set of optimisers (see 'method' arg under __init__)

    TODO
    ----
    _gen_optim_list : add check for list of optim args? 1/optim?
    _cross_evaluation : allow vectorized verion for fast evaluation?
    gen_init_circuits : Update init points to take into accout domain 
        (see ut.get_default_args)
    gen_init_circuits : Making something like this automatic for quick 
        compling measurement circuits
    init_optimisers : allow for more than one initial 
    next_evaluation_circuits  : Put interface for _compute_next_ev....
    update & init_optimisers : generalise beyond BO optimisers
    update : implement by-hand updating of dynamic weights?
    """

    def __init__(self, 
                 cost_objs,
                 optimizer, # to replace default BO, extend to list? 
                 optimizer_args, # also allow list of input args
                 method = 'shared',
                 share_init = True,
                 nb_init = 10,
                 nb_optim = 10,
                 ): 
        """ 
        Parameters
        ----------
        cost_objs : list of Cost objects
            Cost functions being max/minimised by the internal optimsers
        optimizer : **class/list of classes under some interface?**
            Class(es) of individual internal optimiser objects
        optimizer_args : { dict, list of dicts }
            The initialisation args to pass to the internal optimisation 
            objects, either a single set to be passed to all or a list to
            be distributed over the optimisers
        method : {'independent','shared','random','left','right'}
            This controls the evaluation sharing of the internal optimiser 
            objects, cases:
                'independent' : The optimiser do not share data, each only 
                    recieves its own evaluations.
                'shared' :  Each optimiser obj gains access to evaluations 
                    of all the others. 
                'random1' : The optimsers do not get the evaluations others 
                    have requested, but in addition to their own they get an 
                    equivalent number of randomly chosen parameter points 
                'random2' : The optimisers do not get the evaluations others 
                    have requested, but in addition to their own they get an 
                    equivalent number of randomly chosen parameter points. 
                    These points are not chosen fully at random, but instead 
                    if x1 and x2 are opt[1] and opt[2]'s chosen evaluations 
                    respectively then opt[1] get an additional point y2 that 
                    is |x2-x1| away from x1 but in a random direction, 
                    similar for opt[2], etc. (Only really relevant to BO.)
                'left', 'right' : Implement information sharing but in a 
                    directional way, so that (using 'left' as an example) 
                    opt[1] gets its evaluation as well as opt[0]; opt[2] gets 
                    its point as well as opt[1] and opt[0], etc. To ensure all 
                    BO's get an equal number of evaluations this is padded 
                    with random points. These points are not chosen fully at 
                    random, they are chosen in the same way as 'random2' 
                    described above. (Only really relevant to BO.)
        share_init : boolean, optional
            Do the optimiser objects share initialisation data, or does each
            generate their own set?
        nb_init : int or keyword 'max', default 'max'
            (BO) Sets the number of initial data points to feed into the BO 
            before starting iteration rounds. If set to 'max' it will 
            generate the maximum number of initial points such that it 
            submits `init_jobs` worth of circuits to a qiskit backend.
        init_jobs : int, default 1
            (BO) The number of qiskit jobs to use to generate initial data. 
            (Most real device backends accept up to 900 circuits in one job.)
        """
        # make (almost certainly) unique id
        self._prefix = ut.gen_random_str(5)

        # check the method arg is recognised
        if not method in ['independent','shared','left','right']:
            print('method '+f'{method}'+' not recognised, please choose: '
                +'"independent", "shared", "left" or "right".',file=sys.stderr)
            raise ValueError
        elif method in ['random1','random2']:
            raise NotImplementedError

        # store inputs
        self.cost_objs = cost_objs
        self.optimizer = optimizer
        self.optimizer_args = optimizer_args
        self.method = method
        self._share_init = share_init
        self.nb_init = nb_init
        self.nb_optim = nb_optim
        
        # make internal assets
        self.optim_list = self._gen_optim_list()
        self._sharing_matrix = self._gen_sharing_matrix()
        self.circs_to_exec = None
        self._parallel_x = {}
        self._parallel_id = {}
        self._last_results_obj = None
        
        # unused currently
        self._initialised = False
    
    
    def _gen_optim_list(self):
        """ 
        Generate the list of internal optimser objects

        Comments:
        ---------
        Not really needed as a whole seperate function for now, but might be 
        useful dealing with different types of optmizers
        """
        optim_list =  [self.optimizer(**self.optimizer_args) for ii in range(len(self.cost_objs))]
        return optim_list
    
    
    def _gen_sharing_matrix(self):
        """ 
        Generate the sharing tuples based on sharing mode
        """
        nb_optim = len(self.optim_list)
        if self.method == 'shared':
            return [(ii, jj, jj) for ii in range(nb_optim) for jj in range(nb_optim)]
        elif self.method == 'independent':
            return [(ii, ii, ii) for ii in range(nb_optim)]
        elif self.method == 'left':
            tuples = []
            for consumer_idx in range(nb_optim):
                for generator_idx in range(nb_optim):
                    if consumer_idx >= generator_idx:
                        # higher indexed optims consume the evaluations generated by
                        # lower indexed optims
                        tuples.append((consumer_idx,generator_idx,generator_idx))
                    else:
                        # lower indexed optims generate extra 'padding' evaluations so
                        # that they recieve the same number of new data points
                        tuples.append((consumer_idx,consumer_idx,generator_idx))
            # sanity check
            assert len(tuples)==nb_optim*nb_optim
            return tuples
        elif self.method == 'right':
            tuples = []
            for consumer_idx in range(nb_optim):
                for generator_idx in range(nb_optim):
                    if consumer_idx <= generator_idx:
                        # higher indexed optims consume the evaluations generated by
                        # lower indexed optims
                        tuples.append((consumer_idx,generator_idx,generator_idx))
                    else:
                        # lower indexed optims generate extra 'padding' evaluations so
                        # that they recieve the same number of new data points
                        tuples.append((consumer_idx,consumer_idx,generator_idx))
            # sanity check
            assert len(tuples)==nb_optim*nb_optim
            return tuples


    def _get_padding_circuits(self):
        """
        Different sharing modes e.g. 'left' and 'right' require padding
        of the evaluations requested by the optimisers with other random
        points, generate those circuits here
        """
        def _find_min_dist(a,b):
            """
            distance is euclidean distance, but since the values are angles we want to
            minimize the (element-wise) differences over optionally shifting one of the
            points by ±2\pi
            """
            disp_vector = np.minimum((a-b)**2,((a+2*np.pi)-b)**2)
            disp_vector = np.minimum(disp_vector,((a-2*np.pi)-b)**2)
            return np.sqrt(np.sum(disp_vector))

        circs_to_exec = []
        for consumer_idx,requester_idx,pt_idx in self._sharing_matrix:
            # case where we need to generate a new evaluation
            if (consumer_idx==requester_idx) and not (requester_idx==pt_idx):

                # get the points that the two optimsers indexed by
                # (`consumer_idx`==`requester_idx`) and `pt_idx` chose for their evals
                generator_pt = self._parallel_x[requester_idx,requester_idx]
                pt = self._parallel_x[pt_idx,pt_idx]
                # separation between the points
                dist = _find_min_dist(generator_pt,pt)
                
                # generate random vector in N-d space then scale it to have length we want, 
                # using 'Hypersphere Point Picking' Gaussian approach
                random_displacement = np.random.normal(size=self.cost_objs[requester_idx].ansatz.nb_params)
                random_displacement = random_displacement * dist/np.sqrt(np.sum(random_displacement**2))
                # element-wise modulo 2\pi
                new_pt = np.mod(generator_pt+random_displacement,2*np.pi)

                # make new circuit
                this_id = ut.gen_random_str(8)
                named_circs = ut.prefix_to_names(self.cost_objs[requester_idx].meas_circuits, 
                    this_id)
                circs_to_exec += cost.bind_params(named_circs, new_pt, 
                    self.cost_objs[requester_idx].ansatz.params)
                self._parallel_id[requester_idx,pt_idx] = this_id
                self._parallel_x[requester_idx,pt_idx] = new_pt

        return circs_to_exec


    def _cross_evaluation(self, 
                          cst_eval_idx, 
                          optim_requester_idx, 
                          point_idx=None, 
                          results_obj=None):
        """ 
        Evaluate the results of an experiment allowing sharing of data 
        between the different internal optimisers

        Parameters
        ----------
        cst_eval_idx : int
            Index of the optim/cost function that we will evaluate the 
            point against
        optim_requester_idx : int
            Index of the optim that requested the point being considered
        point_idx : int, optional, defaults to optim_requester_idx
            Subindex of the point inside the set of points that optim 
            optim_requester_idx requested
        results_obj : Qiskit results obj, optional, defaults to last got
            The experiment results to use
        """
        if results_obj is None:
            results_obj = self._last_results_obj
        if point_idx is None:
            point_idx = optim_requester_idx
        circ_name = self._parallel_id[optim_requester_idx,point_idx]
        cost_obj = self.cost_objs[cst_eval_idx]
        x = self._parallel_x[optim_requester_idx,point_idx]
        y = cost_obj.evaluate_cost(results_obj, name = circ_name)
        #print(f'{cst_eval_idx}'+' '+f'{optim_requester_idx}'+' '+f'{point_idx}'+':'+f'{circ_name}')
        return x, y
    

    def gen_init_circuits(self):
        """ 
        Generates circuits to gather initialisation data for the optimizers
        """
        circs_to_exec = []
        if self._share_init:
            cost_list = [self.cost_objs[0]] # maybe run compatability check here? 
        else:
            cost_list = self.cost_objs
        for cst_idx,cst in enumerate(cost_list):
            meas_circuits = cst.meas_circuits
            qk_params = meas_circuits[0].parameters
            points = 2*pi*np.random.rand(self.nb_init, len(qk_params))
            #self._parallel_x.update({ (cst_idx,p_idx):p for p_idx,p in enumerate(points) })
            for pt_idx,pt in enumerate(points):
                this_id = ut.gen_random_str(8)
                named_circs = ut.prefix_to_names(meas_circuits, this_id)
                circs_to_exec += cost.bind_params(named_circs, pt, qk_params)
                self._parallel_x[cst_idx,pt_idx] = pt
                self._parallel_id[cst_idx,pt_idx] = this_id
        self.circs_to_exec = circs_to_exec
        return circs_to_exec
    
    
    def init_optimisers(self, results_obj): 
        """ 
        Take results object to initalise the internal optimisers 

        Parameters
        ----------
        results_obj : Qiskit results obj
            The experiment results to use
        """
        self._last_results_obj= results_obj
        nb_optim = len(self.optim_list)
        nb_init = self.nb_init
        if self._share_init:
            sharing_matrix = [(cc,0,run) for cc in range(nb_optim) for run in range(nb_init)]
        else:
            sharing_matrix = [(cc,cc,run) for cc in range(nb_optim) for run in range(nb_init)]
        for evl, req, run in sharing_matrix:
            x, y = self._cross_evaluation(evl, req, run)
            opt = self.optim_list[evl]
            opt.X = np.vstack((opt.X, x))
            opt.Y = np.vstack((opt.Y, y))
        [opt.run_optimization(max_iter = 0, eps = 0) for opt in self.optim_list]
            

    def next_evaluation_circuits(self, x_new=None):
        """ 
        Return the set of executable (i.e. transpiled and bound) quantum 
        circuits that will carry out cost function evaluations at the 
        points requested by each of the internal optimisers
        
        Parameters
        ----------
        x_new : list of x vals, optional
            An iterable with exactly 1 param point per cost function, if None
            is passed the function will query the internal optimisers
        """
        self._parallel_id = {}
        self._parallel_x = {}
        if x_new is None:
            x_new = np.atleast_2d(np.squeeze([opt._compute_next_evaluations() for opt in self.optim_list]))
        circs_to_exec = []
        for cst_idx,(cst,pt) in enumerate(zip(self.cost_objs, x_new)):
            this_id = ut.gen_random_str(8)
            named_circs = ut.prefix_to_names(cst.meas_circuits, this_id)
            circs_to_exec += cost.bind_params(named_circs, pt, cst.meas_circuits[0].parameters)
            self._parallel_id[cst_idx,cst_idx] = this_id
            self._parallel_x[cst_idx,cst_idx] = pt
        circs_to_exec = circs_to_exec + self._get_padding_circuits()

        # sanity check on number of circuits generated
        if self.method in ['independent','shared']:
            assert len(self._parallel_id.keys())==len(self.cost_objs),('Should have '
                +f'{len(self.cost_objs)}'+' circuits, but instead have '
                +f'{len(self._parallel_id.keys())}')
        elif self.method in ['random1','random2']:
            assert len(self._parallel_id.keys())==len(self.cost_objs)**2,('Should have '
                +f'{len(self.cost_objs)**2}'+' circuits, but instead have '
                +f'{len(self._parallel_id.keys())}')
        elif self.method in ['left','right']:
            assert len(self._parallel_id.keys())==len(self.cost_objs)*(len(self.cost_objs)+1)//2,('Should have '
                +f'{len(self.cost_objs)*(len(self.cost_objs)+1)//2}'
                +' circuits, but instead have '+f'{len(self._parallel_id.keys())}')

        self.circs_to_exec = circs_to_exec
        return circs_to_exec
            
    

    def update(self, results_obj):
        """ 
        Update the internal state of the optimisers, currently specific
        to Bayesian optimisers
            
        Parameters
        ----------
        results_obj : Qiskit results obj
            The experiment results to use
        """
        self._last_results_obj = results_obj
        for evl, req, par in self._sharing_matrix:
            x, y = self._cross_evaluation(evl, req, par)
            opt = self.optim_list[evl]
            opt.X = np.vstack((opt.X, x))
            opt.Y = np.vstack((opt.Y, y))

        for opt in self.optim_list:
            opt._update_model(opt.normalization_type)

