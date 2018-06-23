import threading
import sys
import os
sys.path.insert(0, os.path.abspath('../'))
sys.path.insert(0, os.path.abspath('../ConsumptionSaving'))
sys.path.insert(0, os.path.abspath('./'))

import ConsumerParameters as Params       # Parameters for a consumer type
import ConsIndShockModel as Model         # Consumption-saving model with idiosyncratic shocks
from HARKutilities import plotFuncs, plotFuncsDer # Basic plotting tools
from time import clock
import numpy as np
from copy import deepcopy

def f():
    print 'thread function'
    return

def g(agent):
    agent.updateSolutionTerminal()
    agent.solve()
    agent.unpackcFunc()

if __name__ == '__main__':
    for i in range(3):
        t = threading.Thread(target=f)
        t.start()
        
    type_count = 4    # Number of values of CRRA to solve
    
    # Make the basic type that we'll use as a template.
    # The basic type has an artificially dense assets grid, as the problem to be
    # solved must be sufficiently large for multithreading to be faster than
    # single-threading (looping), due to overhead.
    BasicType = Model.IndShockConsumerType(**Params.init_idiosyncratic_shocks)
    BasicType.cycles = 0
    BasicType(aXtraMax  = 100, aXtraCount = 64)
    BasicType(vFuncBool = False, CubicBool = True)
    BasicType.updateAssetsGrid()
    
    # Make many copies of the basic type, each with a different risk aversion
    BasicType.vFuncBool = False # just in case it was set to True above
    my_agent_list = []
    CRRA_list = np.linspace(1,8,type_count) # All the values that CRRA will take on
    for i in range(type_count):
        this_agent = deepcopy(BasicType)   # Make a new copy of the basic type
        this_agent.assignParameters(CRRA = CRRA_list[i]) # Give it a unique CRRA value
        my_agent_list.append(this_agent)   # Add it to the list of agent types
    
    # Solve the types using threading
    t0 = clock()
    my_threads = []
    for i in range(type_count):
        t = threading.Thread(target=g, args=(my_agent_list[i],))
        t.start()
        my_threads.append(t)
    
    for t in my_threads:
        t.join()
    t1 = clock()
    print('That took ' + str(t1-t0) + ' seconds.')
        
    # Plot the consumption functions for all types on one figure
    plotFuncs([this_type.cFunc[0] for this_type in my_agent_list],0,5)
    
        
    