# -*- coding: utf-8 -*-
"""
Created on Thu Jun 09 13:14:47 2016

@author: lowd
"""

import sys 
sys.path.insert(0,'../')
sys.path.insert(0,'../ConsumptionSavingModel')

from copy import copy, deepcopy
import numpy as np
from ConsumptionSavingModel import ConsumptionSavingSolverENDG, ValueFunc, MargValueFunc, ConsumerSolution
from ConsumptionSavingModel import ConsumerType as ConsumptionSavingModelType
from HARKcore import AgentType, Solution, NullFunc
from HARKutilities import warnings  # Because of "patch" to warnings modules
from HARKinterpolation import CubicInterp, LowerEnvelope, LinearInterp
from HARKsimulation import drawMeanOneLognormal, drawBernoulli
from HARKutilities import approxLognormal, approxMeanOneLognormal, addDiscreteOutcomeConstantMean,\
                          combineIndepDstns, makeGridExpMult, CRRAutility, CRRAutilityP, \
                          CRRAutilityPP, CRRAutilityP_inv, CRRAutility_invP, CRRAutility_inv, \
                          CRRAutilityP_invP


utility       = CRRAutility
utilityP      = CRRAutilityP
utilityPP     = CRRAutilityPP
utilityP_inv  = CRRAutilityP_inv
utility_invP  = CRRAutility_invP
utility_inv   = CRRAutility_inv
utilityP_invP = CRRAutilityP_invP






















class ConsumptionSavingSolverMarkov(ConsumptionSavingSolverENDG):
    '''
    A class to solve a single period consumption-saving problem with risky income
    and stochastic transitions between discrete states, in a Markov fashion.
    Extends ConsumptionSavingSolverENDG, with identical inputs but for a discrete
    Markov state, whose transition rule is summarized in MrkvArray.  Markov
    states can differ in their interest factor, permanent growth factor, and
    income distribution, so the inputs Rfree, PermGroFac, and IncomeDstn are
    now arrays or lists specifying those values in each (succeeding) Markov state.
    '''
    def __init__(self,solution_next,IncomeDstn_list,LivPrb,DiscFac,
                      CRRA,Rfree_list,PermGroFac_list,MrkvArray,BoroCnstArt,
                      aXtraGrid,vFuncBool,CubicBool):
        '''
        Constructor for a new solver for a one period problem with risky income
        and transitions between discrete Markov states (assume there are N states).
        
        Parameters
        ----------
        solution_next : ConsumerSolution
            The solution to next period's one period problem.
        IncomeDstn_list : [[np.array]]
            A length N list of income distributions in each succeeding Markov
            state.  Each income distribution contains three arrays of floats,
            representing a discrete approximation to the income process at the
            beginning of the succeeding period. Order: event probabilities,
            permanent shocks, transitory shocks.
        LivPrb : float
            Survival probability; likelihood of being alive at the beginning of
            the succeeding period.    
        DiscFac : float
            Intertemporal discount factor for future utility.        
        CRRA : float
            Coefficient of relative risk aversion.
        Rfree_list : np.array
            Risk free interest factor on end-of-period assets for each Markov
            state in the succeeding period.
        PermGroGac_list : float
            Expected permanent income growth factor at the end of this period
            for each Markov state in the succeeding period.
        MrkvArray : numpy.array
            An NxN array representing a Markov transition matrix between discrete
            states.  The i,j-th element of MrkvArray is the probability of
            moving from state i in period t to state j in period t+1.
        BoroCnstArt: float or None
            Borrowing constraint for the minimum allowable assets to end the
            period with.  If it is less than the natural borrowing constraint,
            then it is irrelevant; BoroCnstArt=None indicates no artificial bor-
            rowing constraint.
        aXtraGrid: np.array
            Array of "extra" end-of-period asset values-- assets above the
            absolute minimum acceptable level.
        vFuncBool: boolean
            An indicator for whether the value function should be computed and
            included in the reported solution.
        CubicBool: boolean
            An indicator for whether the solver should use cubic or linear inter-
            polation.
                        
        Returns
        -------
        None
        '''
        # Set basic attributes of the problem
        ConsumptionSavingSolverENDG.assignParameters(self,solution_next,np.nan,
                                                     LivPrb,DiscFac,CRRA,np.nan,np.nan,
                                                     BoroCnstArt,aXtraGrid,vFuncBool,CubicBool)
        self.defineUtilityFunctions()
        
        # Set additional attributes specific to the Markov model
        self.IncomeDstn_list      = IncomeDstn_list
        self.Rfree_list           = Rfree_list
        self.PermGroFac_list      = PermGroFac_list
        assert False
        self.StateCount           = len(IncomeDstn_list)
        self.MrkvArray            = MrkvArray

    def solve(self):
        '''
        Solve the one period problem of the consumption-saving model with a Markov state.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        solution : ConsumerSolution
            The solution to the single period consumption-saving problem. Includes
            a consumption function cFunc (using cubic or linear splines), a marg-
            inal value function vPfunc, a minimum acceptable level of normalized
            market resources mNrmMin, normalized human wealth hNrm, and bounding
            MPCs MPCmin and MPCmax.  It might also have a value function vFunc
            and marginal marginal value function vPPfunc.  All of these attributes
            are lists or arrays, with elements corresponding to the current
            Markov state.  E.g. solution.cFunc[0] is the consumption function
            when in the i=0 Markov state this period.
        '''
        # Find the natural borrowing constraint in each current state
        self.defBoundary()
        
        # Initialize end-of-period (marginal) value functions
        self.EndOfPrdvFunc_list  = []
        self.EndOfPrdvPfunc_list = []
        self.ExIncNext           = np.zeros(self.StateCount) + np.nan # expected income conditional on the next state
        self.WorstIncPrbAll      = np.zeros(self.StateCount) + np.nan # probability of getting the worst income shock in each next period state

        # Loop through each next-period-state and calculate the end-of-period
        # (marginal) value function
        for j in range(self.StateCount):
            # Condition values on next period's state (and record a couple for later use)
            self.conditionOnState(j)
            self.ExIncNext[j]      = np.dot(self.ShkPrbsNext,
                                            self.PermShkValsNext*self.TranShkValsNext)
            self.WorstIncPrbAll[j] = self.WorstIncPrb
            
            # Construct the end-of-period marginal value function conditional
            # on next period's state and add it to the list of value functions
            EndOfPrdvPfunc_cond = self.makeEndOfPrdvPfuncCond()
            self.EndOfPrdvPfunc_list.append(EndOfPrdvPfunc_cond)
            
            # Construct the end-of-period value functional conditional on next
            # period's state and add it to the list of value functions
            if self.vFuncBool:
                EndOfPrdvFunc_cond = self.makeEndOfPrdvFuncCond()
                self.EndOfPrdvFunc_list.append(EndOfPrdvFunc_cond)
                        
        # EndOfPrdvP_cond is EndOfPrdvP conditional on *next* period's state.
        # Take expectations to get EndOfPrdvP conditional on *this* period's state.
        self.calcEndOfPrdvP()
                
        # Calculate the bounding MPCs and PDV of human wealth for each state
        self.calcHumWealthAndBoundingMPCs()
        
        # Find consumption and market resources corresponding to each end-of-period
        # assets point for each state (and add an additional point at the lower bound)
        aNrm = np.asarray(self.aXtraGrid)[np.newaxis,:] + np.array(self.BoroCnstNat_list)[:,np.newaxis]
        self.getPointsForInterpolation(self.EndOfPrdvP,aNrm)
        cNrm = np.hstack((np.zeros((self.StateCount,1)),self.cNrmNow))
        mNrm = np.hstack((np.reshape(self.mNrmMin_list,(self.StateCount,1)),self.mNrmNow))
        
        # Package and return the solution for this period
        self.BoroCnstNat = self.BoroCnstNat_list
        solution = self.makeSolution(cNrm,mNrm)
        return solution
        
    def defBoundary(self):
        '''
        Find the borrowing constraint for each current state and save it as an
        attribute of self for use by other methods.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        self.BoroCnstNatAll          = np.zeros(self.StateCount) + np.nan
        # Find the natural borrowing constraint conditional on next period's state
        for j in range(self.StateCount):
            PermShkMinNext         = np.min(self.IncomeDstn_list[j][1])
            TranShkMinNext         = np.min(self.IncomeDstn_list[j][2])
            self.BoroCnstNatAll[j] = (self.solution_next.mNrmMin[j] - TranShkMinNext)*\
                                     (self.PermGroFac_list[j]*PermShkMinNext)/self.Rfree_list[j]

        self.BoroCnstNat_list   = np.zeros(self.StateCount) + np.nan
        self.mNrmMin_list       = np.zeros(self.StateCount) + np.nan
        self.BoroCnstDependency = np.zeros((self.StateCount,self.StateCount)) + np.nan
        # The natural borrowing constraint in each current state is the *highest*
        # among next-state-conditional natural borrowing constraints that could
        # occur from this current state.
        for i in range(self.StateCount):
            possible_next_states         = self.MrkvArray[i,:] > 0
            self.BoroCnstNat_list[i]     = np.max(self.BoroCnstNatAll[possible_next_states])
            self.mNrmMin_list[i]         = np.max([self.BoroCnstNat_list[i],self.BoroCnstArt])
            self.BoroCnstDependency[i,:] = self.BoroCnstNat_list[i] == self.BoroCnstNatAll
        # Also creates a Boolean array indicating whether the natural borrowing
        # constraint *could* be hit when transitioning from i to j.
     
    def conditionOnState(self,state_index):
        '''
        Temporarily assume that a particular Markov state will occur in the
        succeeding period, and condition solver attributes on this assumption.
        Allows the solver to construct the future-state-conditional marginal
        value function (etc) for that future state.
        
        Parameters
        ----------
        state_index : int
            Index of the future Markov state to condition on.
        
        Returns
        -------
        none
        '''
        # Set future-state-conditional values as attributes of self
        self.IncomeDstn     = self.IncomeDstn_list[state_index]
        self.Rfree          = self.Rfree_list[state_index]
        self.PermGroFac     = self.PermGroFac_list[state_index]
        self.vPfuncNext     = self.solution_next.vPfunc[state_index]
        self.mNrmMinNow     = self.mNrmMin_list[state_index]
        self.BoroCnstNat    = self.BoroCnstNatAll[state_index]        
        self.setAndUpdateValues(self.solution_next,self.IncomeDstn,self.LivPrb,self.DiscFac)

        # These lines have to come after setAndUpdateValues to override the definitions there
        self.vPfuncNext = self.solution_next.vPfunc[state_index]
        if self.CubicBool:
            self.vPPfuncNext= self.solution_next.vPPfunc[state_index]
        if self.vFuncBool:
            self.vFuncNext  = self.solution_next.vFunc[state_index]
        
    def getGothicvPP(self):
        '''
        Calculates end-of-period marginal marginal value using a pre-defined
        array of next period market resources in self.mNrmNext.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        EndOfPrdvPP = self.DiscFacEff*self.Rfree*self.Rfree*self.PermGroFac**(-self.CRRA-1.0)*\
                      np.sum(self.PermShkVals_temp**(-self.CRRA-1.0)*self.vPPfuncNext(self.mNrmNext)
                      *self.ShkPrbs_temp,axis=0)
        return EndOfPrdvPP
            
    def makeEndOfPrdvFuncCond(self):
        '''
        Construct the end-of-period value function conditional on next period's
        state.  NOTE: It might be possible to eliminate this method and replace
        it with ConsumptionSavingSolverENDG.makeEndOfPrdvFunc, but the self.X_cond
        variables must be renamed.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        EndofPrdvFunc_cond : ValueFunc
            The end-of-period value function conditional on a particular state
            occuring in the next period.            
        '''
        VLvlNext               = (self.PermShkVals_temp**(1.0-self.CRRA)*
                                  self.PermGroFac**(1.0-self.CRRA))*self.vFuncNext(self.mNrmNext)
        EndOfPrdv_cond         = self.DiscFacEff*np.sum(VLvlNext*self.ShkPrbs_temp,axis=0)
        EndOfPrdvNvrs_cond     = self.uinv(EndOfPrdv_cond)
        EndOfPrdvNvrsP_cond    = self.EndOfPrdvP_cond*self.uinvP(EndOfPrdv_cond)
        EndOfPrdvNvrs_cond     = np.insert(EndOfPrdvNvrs_cond,0,0.0)
        EndOfPrdvNvrsP_cond    = np.insert(EndOfPrdvNvrsP_cond,0,EndOfPrdvNvrsP_cond[0])
        aNrm_temp              = np.insert(self.aNrm_cond,0,self.BoroCnstNat)
        EndOfPrdvNvrsFunc_cond = CubicInterp(aNrm_temp,EndOfPrdvNvrs_cond,EndOfPrdvNvrsP_cond)
        EndofPrdvFunc_cond     = ValueFunc(EndOfPrdvNvrsFunc_cond,self.CRRA)        
        return EndofPrdvFunc_cond
        
            
    def makeEndOfPrdvPfuncCond(self):
        '''
        Construct the end-of-period marginal value function conditional on next
        period's state.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        EndofPrdvPfunc_cond : MargValueFunc
            The end-of-period marginal value function conditional on a particular
            state occuring in the succeeding period.
        '''
        # Get data to construct the end-of-period marginal value function (conditional on next state) 
        self.aNrm_cond      = self.prepareToGetGothicvP()  
        self.EndOfPrdvP_cond= self.getGothicvP()
        EndOfPrdvPnvrs_cond = self.uPinv(self.EndOfPrdvP_cond) # "decurved" marginal value
        if self.CubicBool:
            EndOfPrdvPP_cond = self.getGothicvPP()
            EndOfPrdvPnvrsP_cond = EndOfPrdvPP_cond*self.uPinvP(self.EndOfPrdvP_cond) # "decurved" marginal marginal value
        
        # Construct the end-of-period marginal value function conditional on the next state.
        if self.CubicBool:
            EndOfPrdvPnvrsFunc_cond = CubicInterp(self.aNrm_cond,EndOfPrdvPnvrs_cond,
                                                  EndOfPrdvPnvrsP_cond,lower_extrap=True)
        else:
            EndOfPrdvPnvrsFunc_cond = LinearInterp(self.aNrm_cond,EndOfPrdvPnvrs_cond,
                                                   lower_extrap=True)            
        EndofPrdvPfunc_cond = MargValueFunc(EndOfPrdvPnvrsFunc_cond,self.CRRA) # "recurve" the interpolated marginal value function
        return EndofPrdvPfunc_cond
            
    def calcEndOfPrdvP(self):
        '''
        Calculates end of period marginal value (and marginal marginal) value
        at each aXtra gridpoint for each current state, unconditional on the
        future Markov state (i.e. weighting conditional end-of-period marginal
        value by transition probabilities).
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        # Find unique values of minimum acceptable end-of-period assets (and the
        # current period states for which they apply).
        aNrmMin_unique, state_inverse = np.unique(self.BoroCnstNat_list,return_inverse=True)
        self.possible_transitions     = self.MrkvArray > 0
        
        # Calculate end-of-period marginal value (and marg marg value) at each
        # asset gridpoint for each current period state
        EndOfPrdvP                    = np.zeros((self.StateCount,self.aXtraGrid.size))
        EndOfPrdvPP                   = np.zeros((self.StateCount,self.aXtraGrid.size))
        for k in range(aNrmMin_unique.size):
            aNrmMin       = aNrmMin_unique[k]   # minimum assets for this pass
            which_states  = state_inverse == k  # the states for which this minimum applies
            aGrid         = aNrmMin + self.aXtraGrid # assets grid for this pass
            EndOfPrdvP_all  = np.zeros((self.StateCount,self.aXtraGrid.size))
            EndOfPrdvPP_all = np.zeros((self.StateCount,self.aXtraGrid.size))
            for j in range(self.StateCount):
                if np.any(np.logical_and(self.possible_transitions[:,j],which_states)): # only consider a future state if one of the relevant states could transition to it
                    EndOfPrdvP_all[j,:] = self.EndOfPrdvPfunc_list[j](aGrid)
                    if self.CubicBool: # Add conditional end-of-period (marginal) marginal value to the arrays
                        EndOfPrdvPP_all[j,:] = self.EndOfPrdvPfunc_list[j].derivative(aGrid)
            # Weight conditional marginal (marginal) values by transition probs
            # to get unconditional marginal (marginal) value at each gridpoint.
            EndOfPrdvP_temp = np.dot(self.MrkvArray,EndOfPrdvP_all)
            EndOfPrdvP[which_states,:] = EndOfPrdvP_temp[which_states,:] # only take the states for which this asset minimum applies
            if self.CubicBool:
                EndOfPrdvPP_temp = np.dot(self.MrkvArray,EndOfPrdvPP_all)
                EndOfPrdvPP[which_states,:] = EndOfPrdvPP_temp[which_states,:]
                
        # Store the results as attributes of self
        self.EndOfPrdvP = EndOfPrdvP
        if self.CubicBool:
            self.EndOfPrdvPP = EndOfPrdvPP
            
    def calcHumWealthAndBoundingMPCs(self):
        '''
        Calculates human wealth and the maximum and minimum MPC for each current
        period state, then stores them as attributes of self for use by other methods.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        # Upper bound on MPC at lower m-bound
        WorstIncPrb_array = self.BoroCnstDependency*np.tile(np.reshape(self.WorstIncPrbAll,
                            (1,self.StateCount)),(self.StateCount,1))
        temp_array        = self.MrkvArray*WorstIncPrb_array
        WorstIncPrbNow    = np.sum(temp_array,axis=1) # Probability of getting the "worst" income shock and transition from each current state
        ExMPCmaxNext      = (np.dot(temp_array,self.Rfree_list**(1.0-self.CRRA)*
                            self.solution_next.MPCmax**(-self.CRRA))/WorstIncPrbNow)**\
                            (-1.0/self.CRRA)
        self.MPCmaxNow    = 1.0/(1.0 + ((self.DiscFacEff*WorstIncPrbNow)**
                            (1.0/self.CRRA))/ExMPCmaxNext)
        self.MPCmaxEff    = self.MPCmaxNow
        self.MPCmaxEff[self.BoroCnstNat_list < self.mNrmMin_list] = 1.0
        # State-conditional PDV of human wealth
        hNrmPlusIncNext   = self.ExIncNext + self.solution_next.hNrm
        self.hNrmNow      = np.dot(self.MrkvArray,(self.PermGroFac_list/self.Rfree_list)*
                            hNrmPlusIncNext)
        # Lower bound on MPC as m gets arbitrarily large
        temp              = (self.DiscFacEff*np.dot(self.MrkvArray,self.solution_next.MPCmin**
                            (-self.CRRA)*self.Rfree_list**(1.0-self.CRRA)))**(1.0/self.CRRA)
        self.MPCminNow    = 1.0/(1.0 + temp)

    def makeSolution(self,cNrm,mNrm):
        '''
        Construct an object representing the solution to this period's problem.
        
        Parameters
        ----------
        cNrm : np.array
            Array of normalized consumption values for interpolation.  Each row
            corresponds to a Markov state for this period.
        mNrm : np.array
            Array of normalized market resource values for interpolation.  Each
            row corresponds to a Markov state for this period.
        
        Returns
        -------
        solution : ConsumerSolution
            The solution to the single period consumption-saving problem. Includes
            a consumption function cFunc (using cubic or linear splines), a marg-
            inal value function vPfunc, a minimum acceptable level of normalized
            market resources mNrmMin, normalized human wealth hNrm, and bounding
            MPCs MPCmin and MPCmax.  It might also have a value function vFunc
            and marginal marginal value function vPPfunc.  All of these attributes
            are lists or arrays, with elements corresponding to the current
            Markov state.  E.g. solution.cFunc[0] is the consumption function
            when in the i=0 Markov state this period.
        '''
        solution = ConsumerSolution() # An empty solution to which we'll add state-conditional solutions
        # Calculate the MPC at each market resource gridpoint in each state (if desired)
        if self.CubicBool:
            dcda          = self.EndOfPrdvPP/self.uPP(np.array(self.cNrmNow))
            MPC           = dcda/(dcda+1.0)
            self.MPC_temp = np.hstack((np.reshape(self.MPCmaxNow,(self.StateCount,1)),MPC))  
            interpfunc    = self.makeCubiccFunc            
        else:
            interpfunc    = self.makeLinearcFunc
        
        # Loop through each current period state and add its solution to the overall solution
        for i in range(self.StateCount):
            # Set current-period-conditional human wealth and MPC bounds
            self.hNrmNow_j   = self.hNrmNow[i]
            self.MPCminNow_j = self.MPCminNow[i]
            if self.CubicBool:
                self.MPC_temp_j  = self.MPC_temp[i,:]
                
            # Construct the consumption function by combining the constrained and unconstrained portions
            self.cFuncNowCnst = LinearInterp([self.mNrmMin_list[i], self.mNrmMin_list[i]+1.0],
                                             [0.0,1.0])
            cFuncNowUnc       = interpfunc(mNrm[i,:],cNrm[i,:])
            cFuncNow          = LowerEnvelope(cFuncNowUnc,self.cFuncNowCnst)

            # Make the marginal value function and pack up the current-state-conditional solution
            vPfuncNow     = MargValueFunc(cFuncNow,self.CRRA)
            solution_cond = ConsumerSolution(cFunc=cFuncNow, vPfunc=vPfuncNow, 
                                             mNrmMin=self.mNrmMinNow)
            if self.CubicBool: # Add the state-conditional marginal marginal value function (if desired)    
                solution_cond = self.addvPPfunc(solution_cond)

            # Add the current-state-conditional solution to the overall period solution
            solution.appendSolution(solution_cond)
        
        # Add the lower bounds of market resources, MPC limits, human resources,
        # and the value functions to the overall solution
        solution.mNrmMin = self.mNrmMin_list
        solution         = self.addMPCandHumanWealth(solution)
        if self.vFuncBool:
            vFuncNow = self.makevFunc(solution)
            solution.vFunc = vFuncNow
        
        # Return the overall solution to this period
        return solution
        
    
    def makeLinearcFunc(self,mNrm,cNrm):
        '''
        Make a linear interpolation to represent the (unconstrained) consumption
        function conditional on the current period state.
        
        Parameters
        ----------
        mNrm : np.array
            Array of normalized market resource values for interpolation.
        cNrm : np.array
            Array of normalized consumption values for interpolation.
                
        Returns
        -------
        cFuncUnc: an instance of HARKinterpolation.LinearInterp
        '''
        cFuncUnc = LinearInterp(mNrm,cNrm,self.MPCminNow_j*self.hNrmNow_j,self.MPCminNow_j)
        return cFuncUnc


    def makeCubiccFunc(self,mNrm,cNrm):
        '''
        Make a cubic interpolation to represent the (unconstrained) consumption
        function conditional on the current period state.
        
        Parameters
        ----------
        mNrm : np.array
            Array of normalized market resource values for interpolation.
        cNrm : np.array
            Array of normalized consumption values for interpolation.
                
        Returns
        -------
        cFuncUnc: an instance of HARKinterpolation.CubicInterp
        '''
        cFuncUnc = CubicInterp(mNrm,cNrm,self.MPC_temp_j,self.MPCminNow_j*self.hNrmNow_j,
                               self.MPCminNow_j)
        return cFuncUnc
        
    def makevFunc(self,solution):
        '''
        Construct the value function for each current state.
        
        Parameters
        ----------
        solution : ConsumerSolution
            The solution to the single period consumption-saving problem. Must
            have a consumption function cFunc (using cubic or linear splines) as
            a list with elements corresponding to the current Markov state.  E.g.
            solution.cFunc[0] is the consumption function when in the i=0 Markov
            state this period.
            
        Returns
        -------
        vFuncNow : [ValueFunc]
            A list of value functions (defined over normalized market resources
            m) for each current period Markov state.
        '''
        vFuncNow = [] # Initialize an empty list of value functions
        # Loop over each current period state and construct the value function
        for i in range(self.StateCount):
            # Make state-conditional grids of market resources and consumption
            mNrmMin       = self.mNrmMin_list[i]
            mGrid         = mNrmMin + self.aXtraGrid
            cGrid         = solution.cFunc[i](mGrid)
            aGrid         = mGrid - cGrid
            
            # Calculate end-of-period value at each gridpoint
            EndOfPrdv_all   = np.zeros((self.StateCount,self.aXtraGrid.size))
            for j in range(self.StateCount):
                if self.possible_transitions[i,j]:
                    EndOfPrdv_all[j,:] = self.EndOfPrdvFunc_list[j](aGrid)
            EndOfPrdv     = np.dot(self.MrkvArray[i,:],EndOfPrdv_all)
            
            # Calculate (normalized) value and marginal value at each gridpoint
            vNrmNow       = self.u(cGrid) + EndOfPrdv
            vPnow         = self.uP(cGrid)
            
            # Make a "decurved" value function with the inverse utility function
            vNvrs        = self.uinv(vNrmNow) # value transformed through inverse utility
            vNvrsP       = vPnow*self.uinvP(vNrmNow)
            mNrm_temp    = np.insert(mGrid,0,mNrmMin) # add the lower bound
            vNvrs        = np.insert(vNvrs,0,0.0)
            vNvrsP       = np.insert(vNvrsP,0,self.MPCmaxEff[i]**(-self.CRRA/(1.0-self.CRRA)))
            MPCminNvrs   = self.MPCminNow[i]**(-self.CRRA/(1.0-self.CRRA))
            vNvrsFunc_i  = CubicInterp(mNrm_temp,vNvrs,vNvrsP,MPCminNvrs*self.hNrmNow[i],MPCminNvrs)
            
            # "Recurve" the decurved value function and add it to the list
            vFunc_i     = ValueFunc(vNvrsFunc_i,self.CRRA)
            vFuncNow.append(vFunc_i)
        return vFuncNow


def solveConsumptionSavingMarkov(solution_next,IncomeDstn,LivPrb,DiscFac,CRRA,Rfree,PermGroFac,
                                 MrkvArray,BoroCnstArt,aXtraGrid,vFuncBool,CubicBool):
    '''
    Solves a single period consumption-saving problem with risky income and
    stochastic transitions between discrete states, in a Markov fashion.  Has
    identical inputs as solveConsumptionSavingENDG, except for a discrete 
    Markov transitionrule MrkvArray.  Markov states can differ in their interest 
    factor, permanent growth factor, and income distribution, so the inputs Rfree, PermGroFac, and
    IncomeDstn are arrays or lists specifying those values in each (succeeding) Markov state.
    
    Parameters
    ----------
    solution_next : ConsumerSolution
        The solution to next period's one period problem.
    IncomeDstn_list : [[np.array]]
        A length N list of income distributions in each succeeding Markov
        state.  Each income distribution contains three arrays of floats,
        representing a discrete approximation to the income process at the
        beginning of the succeeding period. Order: event probabilities,
        permanent shocks, transitory shocks.
    LivPrb : float
        Survival probability; likelihood of being alive at the beginning of
        the succeeding period.    
    DiscFac : float
        Intertemporal discount factor for future utility.        
    CRRA : float
        Coefficient of relative risk aversion.
    Rfree_list : np.array
        Risk free interest factor on end-of-period assets for each Markov
        state in the succeeding period.
    PermGroGac_list : float
        Expected permanent income growth factor at the end of this period
        for each Markov state in the succeeding period.
    MrkvArray : numpy.array
        An NxN array representing a Markov transition matrix between discrete
        states.  The i,j-th element of MrkvArray is the probability of
        moving from state i in period t to state j in period t+1.
    BoroCnstArt: float or None
        Borrowing constraint for the minimum allowable assets to end the
        period with.  If it is less than the natural borrowing constraint,
        then it is irrelevant; BoroCnstArt=None indicates no artificial bor-
        rowing constraint.
    aXtraGrid: np.array
        Array of "extra" end-of-period asset values-- assets above the
        absolute minimum acceptable level.
    vFuncBool: boolean
        An indicator for whether the value function should be computed and
        included in the reported solution.
    CubicBool: boolean
        An indicator for whether the solver should use cubic or linear inter-
        polation.
        
    Returns
    -------
    solution : ConsumerSolution
        The solution to the single period consumption-saving problem. Includes
        a consumption function cFunc (using cubic or linear splines), a marg-
        inal value function vPfunc, a minimum acceptable level of normalized
        market resources mNrmMin, normalized human wealth hNrm, and bounding
        MPCs MPCmin and MPCmax.  It might also have a value function vFunc
        and marginal marginal value function vPPfunc.  All of these attributes
        are lists or arrays, with elements corresponding to the current
        Markov state.  E.g. solution.cFunc[0] is the consumption function
        when in the i=0 Markov state this period.
    '''                                       
    solver = ConsumptionSavingSolverMarkov(solution_next,IncomeDstn,LivPrb,DiscFac,CRRA,Rfree,
                                           PermGroFac,MrkvArray,BoroCnstArt,aXtraGrid,vFuncBool,
                                           CubicBool)              
    solution_now = solver.solve()
    return solution_now             




























class ConsumerType(ConsumptionSavingModelType):
    '''
    An agent in the consumption-saving model.  His problem is defined by a sequence
    of income distributions, survival probabilities, discount factors, and permanent
    income growth rates, as well as time invariant values for risk aversion, the
    interest rate, the grid of end-of-period assets, and how he is borrowing constrained.
    '''    





    def makeIncShkHist(self):
        '''
        Makes histories of simulated income shocks for this consumer type by
        drawing from the discrete income distributions, respecting the Markov
        state for each agent in each period.  Should be run after makeMrkvHist().
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        orig_time = self.time_flow
        self.timeFwd()
        self.resetRNG()
        
        # Initialize the shock histories
        N = self.MrkvArray.shape[0]
        PermShkHist = np.zeros((self.sim_periods,self.Nagents)) + np.nan
        TranShkHist = np.zeros((self.sim_periods,self.Nagents)) + np.nan
        PermShkHist[0,:] = 1.0
        TranShkHist[0,:] = 1.0
        t_idx = 0
        
        # Draw income shocks for each simulated period, respecting the Markov state
        for t in range(1,self.sim_periods):
            MrkvNow = self.MrkvHist[t,:]
            IncomeDstn_list    = self.IncomeDstn[t_idx]
            PermGroFac_list    = self.PermGroFac[t_idx]
            for n in range(N):
                these = MrkvNow == n
                IncomeDstnNow = IncomeDstn_list[n]
                PermGroFacNow = PermGroFac_list[n]
                Events           = np.arange(IncomeDstnNow[0].size) # just a list of integers
                Cutoffs          = np.round(np.cumsum(IncomeDstnNow[0])*np.sum(these))
                top = 0
                # Make a list of event indices that closely matches the discrete income distribution
                EventList        = []
                for j in range(Events.size):
                    bot = top
                    top = Cutoffs[j]
                    EventList += (top-bot)*[Events[j]]
                # Randomly permute the event indices and store the corresponding results
                EventDraws       = self.RNG.permutation(EventList)
                PermShkHist[t,these] = IncomeDstnNow[1][EventDraws]*PermGroFacNow
                TranShkHist[t,these] = IncomeDstnNow[2][EventDraws]
            # Advance the time index, looping if we've run out of income distributions
            t_idx += 1
            if t_idx >= len(self.IncomeDstn):
                t_idx = 0
        
        # Store the results as attributes of self and restore time to its original flow        
        self.PermShkHist = PermShkHist
        self.TranShkHist = TranShkHist
        if not orig_time:
            self.timeRev()
        
            
    def makeMrkvHist(self):
        '''
        Makes a history of simulated discrete Markov states, starting from the
        initial states in markov_init.  Assumes that MrkvArray is constant.

        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        orig_time = self.time_flow
        self.timeFwd()
        self.resetRNG()
        
        # Initialize the Markov state history
        MrkvHist      = np.zeros((self.sim_periods,self.Nagents),dtype=int)
        MrkvNow       = self.Mrkv_init
        MrkvHist[0,:] = MrkvNow
        base_draws    = np.arange(self.Nagents,dtype=float)/self.Nagents + 1.0/(2*self.Nagents)
        
        # Make an array of Markov transition cutoffs
        N = self.MrkvArray.shape[0] # number of states
        Cutoffs = np.cumsum(self.MrkvArray,axis=1)
        
        # Draw Markov transitions for each period
        for t in range(1,self.sim_periods):
            draws_now = self.RNG.permutation(base_draws)
            MrkvNext = np.zeros(self.Nagents) + np.nan
            for n in range(N):
                these = MrkvNow == n
                MrkvNext[these] = np.searchsorted(Cutoffs[n,:],draws_now[these])
            MrkvHist[t,:] = MrkvNext
            MrkvNow = MrkvNext
        
        # Store the results and return time to its original flow
        self.MrkvHist = MrkvHist
        if not orig_time:
            self.timeRev()


    def simOnePrd(self):
        '''
        Simulate a single period of a consumption-saving model with permanent
        and transitory income shocks.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        
        # Unpack objects from self for convenience
        aPrev          = self.aNow
        pPrev          = self.pNow
        TranShkNow     = self.TranShkNow
        PermShkNow     = self.PermShkNow
        RfreeNow   = self.RfreeNow[self.MrkvNow]
        cFuncNow       = self.cFuncNow
        
        # Simulate the period
        pNow    = pPrev*PermShkNow      # Updated permanent income level
        ReffNow = RfreeNow/PermShkNow   # "effective" interest factor on normalized assets
        bNow    = ReffNow*aPrev         # Bank balances before labor income
        mNow    = bNow + TranShkNow     # Market resources after income

        N      = self.MrkvArray.shape[0]            
        cNow   = np.zeros_like(mNow)
        MPCnow = np.zeros_like(mNow)
        for n in range(N):
            these = self.MrkvNow == n
            cNow[these], MPCnow[these] = cFuncNow[n].eval_with_derivative(mNow[these]) # Consumption and maginal propensity to consume

        aNow    = mNow - cNow           # Assets after all actions are accomplished
        
        # Store the new state and control variables
        self.pNow   = pNow
        self.bNow   = bNow
        self.mNow   = mNow
        self.cNow   = cNow
        self.MPCnow = MPCnow
        self.aNow   = aNow





    def advanceIncShks(self):
        '''
        Advance the permanent and transitory income shocks to the next period of
        the shock history objects.
        
        Parameters
        ----------
        none
        
        Returns
        -------
        none
        '''
        self.MrkvNow = self.MrkvHist[self.Shk_idx,:]
        ConsumptionSavingModelType.advanceIncShks()




















    
    

if __name__ == '__main__':
    
    import SetupConsumerParameters as Params
    from HARKutilities import plotFuncsDer, plotFuncs
    from time import clock
    mystr = lambda number : "{:.4f}".format(number)

    do_simulation           = True

    # Make and solve a type that has serially correlated unemployment   

    # Define the Markov transition matrix
    unemp_length = 5
    urate_good = 0.05
    urate_bad = 0.12
    bust_prob = 0.01
    recession_length = 20
    p_reemploy =1.0/unemp_length
    p_unemploy_good = p_reemploy*urate_good/(1-urate_good)
    p_unemploy_bad = p_reemploy*urate_bad/(1-urate_bad)
    boom_prob = 1.0/recession_length
    MrkvArray = np.array([[(1-p_unemploy_good)*(1-bust_prob),p_unemploy_good*(1-bust_prob),
                           (1-p_unemploy_good)*bust_prob,p_unemploy_good*bust_prob],
                          [p_reemploy*(1-bust_prob),(1-p_reemploy)*(1-bust_prob),
                           p_reemploy*bust_prob,(1-p_reemploy)*bust_prob],
                          [(1-p_unemploy_bad)*boom_prob,p_unemploy_bad*boom_prob,
                           (1-p_unemploy_bad)*(1-boom_prob),p_unemploy_bad*(1-boom_prob)],
                          [p_reemploy*boom_prob,(1-p_reemploy)*boom_prob,
                           p_reemploy*(1-boom_prob),(1-p_reemploy)*(1-boom_prob)]])
    
    MarkovType = ConsumerType(**Params.init_consumer_objects)
    xi_dist = approxMeanOneLognormal(MarkovType.TranShkCount, 0.1)
    psi_dist = approxMeanOneLognormal(MarkovType.PermShkCount, 0.1)
    employed_income_dist = combineIndepDstns(psi_dist, xi_dist)
    employed_income_dist = [np.ones(1),np.ones(1),np.ones(1)]
    unemployed_income_dist = [np.ones(1),np.ones(1),np.zeros(1)]
    
    MarkovType.solution_terminal.cFunc = 4*[MarkovType.solution_terminal.cFunc]
    MarkovType.solution_terminal.vFunc = 4*[MarkovType.solution_terminal.vFunc]
    MarkovType.solution_terminal.vPfunc = 4*[MarkovType.solution_terminal.vPfunc]
    MarkovType.solution_terminal.vPPfunc = 4*[MarkovType.solution_terminal.vPPfunc]
    MarkovType.solution_terminal.mNrmMin = 4*[MarkovType.solution_terminal.mNrmMin]
    MarkovType.solution_terminal.MPCmax = np.array(4*[1.0])
    MarkovType.solution_terminal.MPCmin = np.array(4*[1.0])
    
    MarkovType.Rfree = np.array(4*[MarkovType.Rfree])
    MarkovType.PermGroFac = [np.array(4*MarkovType.PermGroFac)]
    
    MarkovType.IncomeDstn = [[employed_income_dist,unemployed_income_dist,employed_income_dist,
                              unemployed_income_dist]]
    MarkovType.MrkvArray = MrkvArray
    MarkovType.time_inv.append('MrkvArray')
    MarkovType.solveOnePeriod = solveConsumptionSavingMarkov
    MarkovType.cycles = 0        
    #MarkovType.vFuncBool = False
    
#    MarkovType.timeFwd()
#    start_time = clock()
#    MarkovType.solve()
#    end_time = clock()
#    print('Solving a Markov consumer took ' + mystr(end_time-start_time) + ' seconds.')
#    print('Consumption functions for each discrete state:')
#    plotFuncs(MarkovType.solution[0].cFunc,0,50)
#    if MarkovType.vFuncBool:
#        print('Value functions for each discrete state:')
#        plotFuncs(MarkovType.solution[0].vFunc,5,50)
#
#    if do_simulation:
#        MarkovType.Mrkv_init = np.zeros(MarkovType.Nagents,dtype=int)
#        MarkovType.makeMrkvHist()
#        MarkovType.makeIncShkHistMrkv()
#        MarkovType.initializeSim()
#        MarkovType.simConsHistory()


