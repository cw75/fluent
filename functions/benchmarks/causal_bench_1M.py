import cloudpickle as cp
import logging
import numpy as np
import random
import sys
import time
import uuid

from anna.functions_pb2 import *
from anna.kvs_pb2 import *
from include.serializer import *
from include.shared import *
from . import utils

zipf = 0
base = 0
sum_probs = {}
sum_probs[0] = 0.0

def get_base(N, skew):
    base = 0.0
    for k in range(1, N+1):
        base += np.power(k, -1*skew)
    return 1 / float(base)



def sample(n, base, sum_probs):
    zipf_value = None
    low = 1
    high = n

    z = random.random()
    while z == 0 or z == 1:
        z = random.random()

    while True:
        mid = int(np.floor((low + high) / 2))
        if sum_probs[mid] >= z and sum_probs[mid - 1] < z:
            zipf_value = mid
            break
        elif sum_probs[mid] >= z:
            high = mid - 1
        else:
            low = mid + 1
        if low > high:
            break
    return zipf_value


def generate_arg_map(functions, connections, num_keys, base, sum_probs):
    arg_map = {}
    keys_read = []

    for func in functions:
        num_parents = 0 
        for conn in connections:
            if conn[1] == func:
                num_parents += 1

        to_generate = 2 - num_parents
        refs = ()
        keys_chosen = []
        while not to_generate == 0:
            # sample key from zipf
            key = sample(num_keys, base, sum_probs)
            key = str(key).zfill(len(str(num_keys)))

            if key not in keys_chosen:
                keys_chosen.append(key)
                refs += (FluentReference(key, False, CROSSCAUSAL),)
                to_generate -= 1
                keys_read.append(key)

        arg_map[func] = refs
        
    return arg_map, list(set(keys_read))

def run(flconn, kvs, mode, segment, params):
    dag_name = 'causal_test'
    functions = ['strmnp1', 'strmnp2', 'strmnp3']
    connections = [('strmnp1', 'strmnp2'), ('strmnp2', 'strmnp3')]
    total_num_keys = 1000000

    if mode == 'create':
        #print("Creating functions and DAG")
        logging.info("Creating functions and DAG")
        ### DEFINE AND REGISTER FUNCTIONS ###
        def strmnp(a,b):
            return '0'.zfill(8)

        cloud_strmnp1 = flconn.register(strmnp, 'strmnp1')
        cloud_strmnp2 = flconn.register(strmnp, 'strmnp2')
        cloud_strmnp3 = flconn.register(strmnp, 'strmnp3')

        if cloud_strmnp1 and cloud_strmnp2 and cloud_strmnp3:
            logging.info('Successfully registered the string manipulation function.')
        else:
            logging.info('Error registering functions.')
            sys.exit(1)

        ### TEST REGISTERED FUNCTIONS ###
        '''refs = ()
        for _ in range(2):
            val = '0'.zfill(8)
            ccv = CrossCausalValue()
            ccv.vector_clock['base'] = 1
            ccv.values.extend([serialize_val(val)])
            k = str(uuid.uuid4())
            print("key name is ", k)
            kvs.put(k, ccv)

            refs += (FluentReference(k, True, CROSSCAUSAL),)

        strmnp_test1 = cloud_strmnp1(*refs).get()
        strmnp_test2 = cloud_strmnp2(*refs).get()
        strmnp_test3 = cloud_strmnp3(*refs).get()
        if strmnp_test1 != '0'.zfill(8) or strmnp_test2 != '0'.zfill(8) or strmnp_test3 != '0'.zfill(8):
            logging.error('Unexpected result from strmnp(v1, v2, v3): %s %s %s' % (str(strmnp_test1), str(strmnp_test2), str(strmnp_test3)))
            sys.exit(1)'''

        #print('Successfully tested functions!')
        logging.info('Successfully tested functions!')

        ### CREATE DAG ###

        success, error = flconn.register_dag(dag_name, functions, connections)

        if not success:
            logging.info('Failed to register DAG: %s' % (ErrorType.Name(error)))
            sys.exit(1)

        #print("Successfully created the DAG")
        logging.info("Successfully created the DAG")
        return [[], 0]

    elif mode == 'zipf':
        logging.info("Creating Probability Table")
        ### CREATE ZIPF TABLE###
        params[0] = 1.5
        params[1] = get_base(total_num_keys, params[0])
        for i in range(1, total_num_keys+1):
            params[2][i] = params[2][i - 1] + (params[1] / np.power(float(i), params[0]))

        logging.info("Created Probability Table with zipf %f" % params[0])
        return [[], 0]

    elif mode == 'run':
        ### RUN DAG ###
        #print('Running DAG')
        logging.info('Running DAG')
        zipf = params[0]
        base = params[1]
        sum_probs = params[2]

        total_time = []

        all_times = []
        all_planner_times = []
        all_execution_times = []

        abort = 0

        for i in range(300*segment, 300*segment + 300):
            cid = str(i).zfill(4)

            logging.info("running client %s" % cid)

            arg_map, read_set = generate_arg_map(functions, connections, total_num_keys, base, sum_probs)

            output = random.choice(read_set)

            start = time.time()

            planner_time = 0.0
            execution_time = 0.0

            res = flconn.call_dag(dag_name, arg_map, True, NORMAL, output, cid)
            tokens = res.split(':')
            while len(tokens) == 3:
                abort += 1
                planner_time += float(tokens[1])
                execution_time += float(tokens[2])
                res = flconn.call_dag(dag_name, arg_map, True, NORMAL, output, cid)
                tokens = res.split(':')
            planner_time += float(tokens[0])
            execution_time += float(tokens[1])

            end = time.time()
            all_times.append((end - start))
            all_planner_times.append(planner_time)
            all_execution_times.append(execution_time)
        logging.info('total abort is %d' % abort)
        return [all_times, all_planner_times, all_execution_times, abort]