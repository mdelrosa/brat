import json

def unpack_json(json_config):
    print('json_config: {}'.format(json_config))
    with open(json_config) as json_file:
        data = json.load(json_file)
        encoded_dims = data['encoded_dims']
        dates = data['dates']
        model_dir = data['model_dir']
        aux_bool = data['aux_bool']
        dim = data['M_1']
        data_format = data['df'] 
        epochs = data['epochs']
        t1_train = data['t1_train']
        t2_train = data['t2_train']
        gpu_num = data['gpu_num'] 
        lstm_latent_bool = data['lstm_latent_bool'] 
        conv_lstm_bool = data['conv_lstm_bool'] 
        print("Loaded json file: {}".format(json_config))
        print("encoded_dims: {} - dates: {} - model_dir: {} - aux_bool: {} - aux_dim: {} - epochs: {} - t1_train: {} - t2_train: {}".format(encoded_dims,dates,model_dir,aux_bool,dim, epochs, t1_train, t2_train)) 
        return [encoded_dims, dates, model_dir, aux_bool, dim, data_format, epochs, t1_train, t2_train, gpu_num, lstm_latent_bool, conv_lstm_bool]

def unpack_compact_json(json_config):
    print('json_config: {}'.format(json_config))
    with open(json_config) as json_file:
        data = json.load(json_file)
        encoded_dim = data['encoded_dim']
        date = data['date']
        model_dir = data['model_dir']
        print("Loaded json file: {}".format(json_config))
        print("encoded_dim: {} - date: {} - model_dir: {}".format(encoded_dim,date,model_dir)) 
        return [encoded_dim, date, model_dir]

def get_dataset_spec(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        dataset_spec = data['dataset_spec']
        print("dataset_spec: {}".format(dataset_spec)) 
        return dataset_spec 

def get_batch_num(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        batch_num = data['batch_num']
        print("batch_num: {}".format(batch_num)) 
        return batch_num 

def get_hyperparams(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        lrs = data['lrs']
        batch_sizes = data['batch_sizes']
        print("lrs: {} - batch_sizes: {}".format(lrs, batch_sizes)) 
        return lrs, batch_sizes 

def get_network_name(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        network_name = data['network_name']
        print("network_name: {}".format(network_name)) 
        return network_name

def get_minmax_file(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        minmax_file = data['minmax_file']
        print("minmax_file: {}".format(minmax_file)) 
        return minmax_file

def get_norm_range(json_config):
    with open(json_config) as json_file:
        data = json.load(json_file)
        norm_range = data['norm_range']
        print("norm_range: {}".format(norm_range)) 
        return norm_range 

def get_keys_from_json(json_config,keys=[],is_bool=False):
    assert len(keys) > 0, "No keys provided"
    out = []
    with open(json_config) as json_file:
        data = json.load(json_file)
        for key in keys:
            temp = data[key]
            if is_bool:
                temp = True if temp==1 else False # handle conversion to bool
            out.append(temp)
            print("{}: {}".format(key, temp)) 
    return out 

