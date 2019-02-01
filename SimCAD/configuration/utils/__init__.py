from datetime import datetime, timedelta
from decimal import Decimal
from copy import deepcopy
from fn.func import curried
import pandas as pd
from SimCAD.utils import rename

from SimCAD.utils import dict_filter, contains_type, curry_pot


from funcy import curry

import pprint

pp = pprint.PrettyPrinter(indent=4)

class TensorFieldReport:
    def __init__(self, config_proc):
        self.config_proc = config_proc

    def create_tensor_field(self, mechanisms, exo_proc, keys=['behaviors', 'states']):
        dfs = [self.config_proc.create_matrix_field(mechanisms, k) for k in keys]
        df = pd.concat(dfs, axis=1)
        for es, i in zip(exo_proc, range(len(exo_proc))):
            df['es' + str(i + 1)] = es
        df['m'] = df.index + 1
        return df


# def s_update(y, x):
#     return lambda step, sL, s, _input: (y, x)
#
#
def state_update(y, x):
    return lambda step, sL, s, _input: (y, x)


def bound_norm_random(rng, low, high):
    res = rng.normal((high+low)/2,(high-low)/6)
    if (res<low or res>high):
        res = bound_norm_random(rng, low, high)
    return Decimal(res)


@curried
def proc_trigger(trigger_step, update_f, step):
    if step == trigger_step:
        return update_f
    else:
        return lambda x: x


t_delta = timedelta(days=0, minutes=0, seconds=30)
def time_step(dt_str, dt_format='%Y-%m-%d %H:%M:%S', _timedelta = t_delta):
    dt = datetime.strptime(dt_str, dt_format)
    t = dt + _timedelta
    return t.strftime(dt_format)


t_delta = timedelta(days=0, minutes=0, seconds=1)
def ep_time_step(s, dt_str, fromat_str='%Y-%m-%d %H:%M:%S', _timedelta = t_delta):
    if s['mech_step'] == 0:
        return time_step(dt_str, fromat_str, _timedelta)
    else:
        return dt_str


def mech_sweep_filter(mech_field, mechanisms):
    mech_dict = dict([(k, v[mech_field]) for k, v in mechanisms.items()])
    return dict([
        (k, dict_filter(v, lambda v: isinstance(v, list))) for k, v in mech_dict.items()
            if contains_type(list(v.values()), list)
    ])


def state_sweep_filter(raw_exogenous_states):
    return dict([(k, v) for k, v in raw_exogenous_states.items() if isinstance(v, list)])

@curried
def sweep_mechs(_type, in_config):
    configs = []
    filtered_mech_states = mech_sweep_filter(_type, in_config.mechanisms)
    if len(filtered_mech_states) > 0:
        for mech, state_dict in filtered_mech_states.items():
            for state, state_funcs in state_dict.items():
                for f in state_funcs:
                    config = deepcopy(in_config)
                    config.mechanisms[mech][_type][state] = f
                    configs.append(config)
                    del config
    else:
        configs = [in_config]

    return configs


@curried
def sweep_states(state_type, states, in_config):
    configs = []
    filtered_states = state_sweep_filter(states)
    if len(filtered_states) > 0:
        for state, state_funcs in filtered_states.items():
            for f in state_funcs:
                config = deepcopy(in_config)
                exploded_states = deepcopy(states)
                exploded_states[state] = f
                if state_type == 'exogenous':
                    config.exogenous_states = exploded_states
                elif state_type == 'environmental':
                    config.env_processes = exploded_states
                configs.append(config)
                del config, exploded_states
    else:
        configs = [in_config]

    return configs


def exo_update_per_ts(ep):
    @curried
    def ep_decorator(f, y, step, sL, s, _input):
        if s['mech_step'] + 1 == 1:
            return curry_pot(f, step, sL, s, _input)
        else:
            return (y, s[y])

    return {es: ep_decorator(f, es) for es, f in ep.items()}


def sweep(params, sweep_f):
    return [rename("sweep_"+sweep_f.__name__+"_"+str(i), curry(sweep_f)(param)) for param, i in zip(params, range(len(params)))]


def zip_sweep_functions(sweep_lists):
    zipped_sweep_lists = []
    it = iter(sweep_lists)
    the_len = len(next(it))
    same_len_ind = all(len(l) == the_len for l in it)
    count_ind = len(sweep_lists) >= 2
    if same_len_ind == True and count_ind == True:
        return list(map(lambda x: list(x), list(zip(*sweep_lists))))
    elif same_len_ind == False or count_ind == False:
        return sweep_lists
    else:
        raise ValueError('lists have different lengths!')


# ToDo: Not producing multiple dicts
def create_sweep_config_list(zipped_sweep_lists, states_dict, state_type_ind='mechs'):
    configs = []
    for f_lists in zipped_sweep_lists:
        new_states_dict = deepcopy(states_dict)
        for f_dict in f_lists:
            if state_type_ind == 'mechs':
                updates = list(f_dict.values()).pop()
                functs = list(updates.values()).pop()

                mech = list(f_dict.keys()).pop()
                update_type = list(updates.keys()).pop()
                sk = list(functs.keys()).pop()
                vf = list(functs.values()).pop()

                new_states_dict[mech][update_type][sk] = vf
            elif state_type_ind == 'exo_proc':
                sk = list(f_dict.keys()).pop()
                vf = list(f_dict.values()).pop()

                new_states_dict[sk] = vf
            else:
                raise ValueError("Incorrect \'state_type_ind\'")

        configs.append(new_states_dict)
        del new_states_dict

    return configs


def parameterize_states(exo_states):
    pp.pprint(exo_states)
    print()
    sweep_lists = []
    for sk, vfs in exo_states.items():
        id_sweep_lists = []
        if isinstance(vfs, list):
            for vf in vfs:
                id_sweep_lists.append({sk: vf})
        if len(id_sweep_lists) != 0:
            sweep_lists.append(id_sweep_lists)

    if len(sweep_lists) == 0:
        return [exo_states]

    pp.pprint(sweep_lists)
    print()

    zipped_sweep_lists = zip_sweep_functions(sweep_lists)
    states_configs = create_sweep_config_list(zipped_sweep_lists, exo_states, "exo_proc")

    return states_configs


def parameterize_mechanism(mechanisms):
    sweep_lists = []
    for mech, update_types in mechanisms.items():
        for update_type, fkv in update_types.items():
            for sk, vfs in fkv.items():
                id_sweep_lists = []
                if isinstance(vfs, list):
                    for vf in vfs:
                        id_sweep_lists.append({mech: {update_type: {sk: vf}}})
                if len(id_sweep_lists) != 0:
                    sweep_lists.append(id_sweep_lists)

    if len(sweep_lists) == 0:
        return [mechanisms]

    zipped_sweep_lists = zip_sweep_functions(sweep_lists)
    mechanisms_configs = create_sweep_config_list(zipped_sweep_lists, mechanisms, "mechs")

    return mechanisms_configs


# def ep_decorator(f, y, step, sL, s, _input):
#     if s['mech_step'] + 1 == 1:
#         return f(step, sL, s, _input)
#     else:
#         return (y, s[y])
#     return {es: ep_decorator(f, es) for es, f in ep.items()}
