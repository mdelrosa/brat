# data_tools.py
# functions for importing/manipulating data for training/validation
import torch
import numpy as np
import pickle as pkl
import h5py
import scipy.io as sio
from .unpack_json import get_keys_from_json
# from QuantizeData import quantize 

from torch.utils.data import Dataset
from tqdm import tqdm

class DatasetToDevice(Dataset):
    def __init__(self, data, length, device):
        self.data = data
        self.len = length
        self.device = device

    def __getitem__(self, index):
        sample_real, sample_imag = torch.Tensor(torch.real(self.data[index, :])).float(), torch.Tensor(torch.imag(self.data[index, :])).float()
        return (sample_real.to(self.device), sample_imag.to(self.device))
        
    def __len__(self):
        return self.len

class CSIDataset(Dataset):
	"""
	Dataset object for channel state information data. If provided, applies random transforms
	"""
	def __init__(self, data, transform=None, device="cpu"):
		# TODO: split individual samples to individual files; load using torch loader
		# TODO: assert input data is torch tensor?
		self.data = data.to(device)
		self.transform = transform

	def __len__(self):
		return self.data.size(0)

	def __getitem__(self, idx):
		sample = self.data[idx,:]
		if self.transform:
			sample = self.transform(sample)
		return sample # TODO: does this need to be a tuple? possibly due to "aux" input (side info, uplink, etc)

# TODO: write this, if useful
# def make_dummy_data(N, n_delay=32, n_angle=32, n_channels=2, data_format="channels_first"):
#     """ make dummy CSI data for proving out different functions """

def make_ar_data(data, p, n_chan=2, n_delay=32, n_angle=32, batch_factor=None, mode="matrix", stride=1, stack=0, backwards=True):
    """
    make time-series of p-length inputs and one-step ahead outputs for vector autoregression

    Parameters
    ----------
    data : array-like, shape (batch_num, T, k)
           full data (train, test, or val)
    p : int
        number of steps for VAR(p)
    n_chan: int
            number of channels in data matrix, typically real/imaginary (i.e., 2)
    n_delay: int
             num of delay values per angle in CSI matrix
    n_angle: int
             num of angular values per delay in CSI matrix
    batch_factor: int
                  divisor to reduce num of elements in CSI matrix
                  divides along batch_num axis of data
    mode: str
          different data types to return based on different linear model assumptions
          "matrix" -- elements in y are lin comb of all other elements in CSI matrices from p timeslots
          "scalar" -- elements in y are lin comb of elements at same (delay,angle) of CSI matrices from p timeslots
          "angular" -- elements in y are lin comb of elements across all angles of CSI matrices from p timeslots
          "angular_corr" -- same premise as 'angular' using empirical correlation matrices 
    stride: int
            increment of AR process steps; (H_0, H_{stride}, ... H_{stride*(p-1)}) to predict H_{stride*p}
    stack: int
           offset index of current stack -- use to grab different subsequences from the same sequence 
    backwards: bool
               If True, then predict last timeslot (y) based on previous p timeslots (Z)
               If False, then p+1-th timeslot (y) based on first p timeslots (Z)
    """

    img_total = n_chan*n_delay*n_angle
    T = data.shape[1]
    e_i = T-1-stack
    assert(stack+p*stride < T)
    # print(f"--- Z_idx: {[i for i in range(e_i-p*stride,e_i,stride)]} , y_idx: {e_i}---")
    # TODO: add stack to other modes
    # TODO: add end-indexing to other modes
    if mode == "matrix":
        Z = np.reshape(data[:,:p*stride:stride,:], (data.shape[0], p*img_total))
        y = data[:,p*stride,:]
    elif mode == "scalar":
        Z = data[:,:p*stride:stride,:]
        Z = np.reshape(np.transpose(Z, (0,2,1)), (data.shape[0]*img_total, p))
        y = data[:,p*stride,:]
        y = np.reshape(y, (data.shape[0]*img_total, 1))
    elif mode == "angular":
        Z = np.reshape(data[:,:p*stride:stride,:], (data.shape[0], p, n_chan, n_delay, n_angle))
        Z = np.reshape(np.transpose(Z, (0,3,1,2,4)), (data.shape[0]*n_delay, p*n_chan*n_angle))
        y = np.reshape(data[:,p*stride,:], (data.shape[0], n_chan, n_delay, n_angle))
        y = np.reshape(np.transpose(y, (0,2,1,3)), (data.shape[0]*n_delay, n_chan*n_angle))
        # elif n_chan == 0:
        #     Z = np.reshape(combine_complex(data[:,:p,:], n_delay, n_angle), (data.shape[0],p,n_delay,n_angle))
        #     Z = np.reshape(np.transpose(Z, (0,2,1,3)), (data.shape[0]*n_delay, p, 2*n_angle))
        #     y = np.reshape(combine_complex(np.expand_dims(data[:,p,:], axis=1), n_delay, n_angle), (data.shape[0]*n_delay,2*n_angle))
    elif mode == "angular_corr_vect":
        Z = np.reshape(combine_complex(data[:,stack:stack+p*stride:stride,:], n_delay, n_angle), (data.shape[0],p,n_delay,n_angle))
        Z = np.reshape(np.transpose(Z, (0,2,1,3)), (data.shape[0]*n_delay, p, n_angle))
        y = np.reshape(combine_complex(np.expand_dims(data[:,p*stride,:], axis=1), n_delay, n_angle), (data.shape[0]*n_delay,n_angle))
    elif mode == "angular_corr" or mode == "multivar_lls":
        # Z = np.reshape(combine_complex(data[:,stack:stack+p*stride:stride,:], n_delay, n_angle), (data.shape[0],p,n_delay,n_angle))
        # y = np.reshape(combine_complex(np.expand_dims(data[:,stack+p*stride,:], axis=1), n_delay, n_angle), (data.shape[0],n_delay,n_angle))
        # (T-stack)-p*stride:(T-stack)+1:stride
        if backwards:
            Z = np.reshape(combine_complex(data[:,e_i-p*stride:e_i:stride,:], n_angle, n_delay, n_chan=n_chan), (data.shape[0],p,n_delay,n_angle))
            y = np.reshape(combine_complex(np.expand_dims(data[:,e_i,:], axis=1), n_angle, n_delay, n_chan=n_chan), (data.shape[0],n_angle,n_delay))
        else:
            Z = np.reshape(combine_complex(data[:,:p*stride:stride,:], n_angle, n_delay, n_chan=n_chan), (data.shape[0],p,n_angle,n_delay))
            y = np.reshape(combine_complex(np.expand_dims(data[:,p*stride,:], axis=1),n_angle, n_delay, n_chan=n_chan), (data.shape[0],n_angle,n_delay))
    if batch_factor != None:
        Z = subsample_batches(Z, batch_factor=batch_factor)
        y = subsample_batches(y, batch_factor=batch_factor)
    return Z, y

def add_batch(data_down, batch, type_str, T, img_channels, img_height, img_width, data_format, n_truncate):
    # concatenate batch data onto end of data
    # Inputs:
    # -> data_up = np.array for uplink
    # -> data_down = np.array for downlink
    # -> batch = mat file to add to np.array
    # -> type_str = part of key to select for training/validation
    x_down = batch['HD_{}'.format(type_str)]    
    x_down = np.reshape(x_down[:,:T,:], get_data_shape(len(x_down), T, img_channels, img_height, img_width, data_format))
    if data_down is None:
        return x_down[:,:,:n_truncate,:] if img_channels > 0 else truncate_flattened_matrix(x_down, img_height, img_width, n_truncate)
    else:
        return np.vstack((data_down,x_down[:,:,:n_truncate,:])) if img_channels > 0 else np.vstack((data_down,truncate_flattened_matrix(x_down, img_height, img_width, n_truncate)))

def split_complex(data,mode=0,T=10):
    if T > 1:
        if mode == 0:
            # default behavior
            re = np.expand_dims(np.real(data).astype('float32'),axis=2) # real portion
            im = np.expand_dims(np.imag(data).astype('float32'),axis=2) # imag portion
            return np.concatenate((re,im),axis=2)
        if mode == 1:
            # written for angular_corr
            re = np.real(data).astype('float32') # real portion
            im = np.imag(data).astype('float32') # imag portion
            return np.concatenate((re,im),axis=1)
    else:
        return np.concatenate((np.expand_dims(np.real(data), axis=1), np.expand_dims(np.imag(data), axis=1)), axis=1)

def truncate_flattened_matrix(x, n_delay, n_angle, n_truncate):
    """
    when img_channels == 0, shape of input is (n_batch, T, 2*n_delay*n_angle)
    need to reshape->truncate->reshape
    """
    n_batch, T, _ = x.shape
    x = np.reshape(x, (n_batch, T, 2, n_delay, n_angle)) # reshape
    x = x[:,:,:,:n_truncate,:] # truncate
    x = np.reshape(x, (n_batch, T, 2*n_truncate*n_angle)) # reshape
    return x

def get_data_shape(samples,T,img_channels,img_height,img_width,data_format):
    if img_channels > 0:
        if(data_format=="channels_last"):
            shape = (samples, T, img_height, img_width, img_channels) if T != 1 else (samples, img_height, img_width, img_channels)
        elif(data_format=="channels_first"):
            shape = (samples, T, img_channels, img_height, img_width) if T != 1 else (samples, img_channels, img_height, img_width)
    else:
        # TODO: get rid of magic number
        shape = (samples, T, 2*img_height*img_width)
    return shape

def subsample_time(data,T,T_max=10):
    """ shorten along T axis """
    if (T < T_max):
        data = data[:,0:T,:]
    return data

def subsample_batches(data,batch_factor=10):
    """ shorten along batch axis """
    N_batch = int(data.shape[0] / batch_factor)
    if N_batch > 0:
        slc = [slice(None)] * len(data.shape) 
        slc[0] = slice(0, N_batch)
        data = data[(slc)]
    return data

def batch_str(base,num):
        return base+str(num)+'.mat'

def stack_data(x1, x2):
    # stack two np arrays with identical shape
    return np.vstack(x1, x2)

def combine_complex(data, height=32, width=32, n_chan=0, T=10):
    assert(n_chan in [0,2])
    if n_chan == 0:
        return data[:,:,:height*width] + data[:,:,height*width:]*1j
    elif n_chan == 2:
        if len(data.shape) == 5:
            return data[:,:,0,:,:] + data[:,:,1,:,:]*1j
        elif len(data.shape) == 4:
            return data[:,0,:,:] + data[:,1,:,:]*1j

def dataset_pipeline_full_batchwise(i_batch, batch_offset, debug_flag, aux_bool, dataset_spec, diff_spec, M_1, img_channels = 2, img_height = 32, img_width = 32, T = 10, train_argv = True, n_truncate=32):
    """
    Load and split dataset according to arguments
    Assumes batch-wise splits (i.e., concatenating along axis=0)
    Assumes dataset_full_key, indicating presence of full CSI matrices 
    Returns batch inexed by i_batch
    mode -> "full" returns non-truncated matrices
         -> "truncate" returns truncated matrices
    Returns: [pow_diff, data_train, data_val]
    """

    x_all = x_all_full = pow_all = None

    assert(len(dataset_spec) == 5)
    dataset_str, dataset_tail, dataset_key, dataset_full_key, val_split = dataset_spec

    batch_str = f"{dataset_str}{i_batch}{dataset_tail}"
    print(f"--- Adding batch #{i_batch} from {batch_str} ---")
    with h5py.File(batch_str, 'r') as f:
        x_t = np.transpose(f[dataset_key][()], [3,2,1,0])
        x_t_full = np.transpose(f[dataset_full_key][()], [3,2,1,0]) 
        f.close()
    # def add_batch_full(data, batch, n_delay, n_angle, n_truncate):
    x_all = add_batch_full(x_all, x_t, img_height, img_width, n_truncate)
    x_all_full = add_batch_full(x_all_full, x_t_full, img_height, img_width, n_truncate)

    if aux_bool:
        aux_t = np.zeros((len(x_all), M_1)).astype('float32')
        data_t = [aux_t, x_all]
    else:
        data_t = x_all

    T = x_all.shape[1]
    for timeslot in range(1,T+1):
        pow_diff, pow_diff_up = load_pow_diff(diff_spec, T=timeslot)
        pow_all = add_batch_pow(pow_all, pow_diff)

    # slice relevant batches 
    i_batch = i_batch - batch_offset
    idx_s = i_batch * x_all.shape[0]
    idx_e = idx_s + x_all.shape[0]
    print(f"--- idx_s: {idx_s}, idx_e: {idx_e} ---")
    pow_all = pow_all[idx_s:idx_e, :]
    
    return [pow_all, data_t, x_all_full]
    # return [pow_all, data_train, data_val, x_train_full, x_val_full]

def dataset_pipeline_p2d(batch_num, batch_offset, batch_size, sz, D, val_split, dataset_spec, dataset_p2d_spec, t_offset=0, img_height = 32, img_width = 32, T = 10):
    """
    Load and split dataset according to arguments

    Assumes batch-wise splits (i.e., concatenating along axis=0)
    Assumes dataset_full_key, indicating presence of full CSI matrices 
    mode -> "full" returns non-truncated matrices
         -> "truncate" returns truncated matrices
    Returns: [pow_diff, data_train, data_val]
    """
    print(f"=== dataset_pipeline_full with T={T} timeslots, t_offset={t_offset} ===")

    assert(len(dataset_spec) == 3)
    dataset_str, dataset_key, dataset_pow_key = dataset_spec

    assert(len(dataset_p2d_spec) == 3)
    dataset_p2d_str, dataset_p2d_tail, dataset_p2d_key = dataset_p2d_spec

    target_key = dataset_key 

    x = np.zeros((batch_num*batch_size, T, img_height, img_width), dtype="complex")
    x_p2d = np.zeros((batch_num*batch_size, T, img_height, img_width), dtype="complex")
    pow_diff = np.zeros((batch_num*batch_size, T))
    for batch in tqdm(range(batch_num), desc="Loading batches"):
    # for batch in range(1,batch_num+1):
        true_batch = 1 + batch + batch_offset
        batch_str = f"{dataset_str}{true_batch}_bs{batch_size}.pkl"
        # ground_truth
        with open(batch_str, 'rb') as f:
            pkl_dict = pkl.load(f)
            x_t = pkl_dict[dataset_key]
            pow_diff_t = pkl_dict[dataset_pow_key]
            f.close()

        # p2d data
        batch_str = f"{dataset_p2d_str}/D{D}/sz{sz}/{dataset_p2d_tail}{true_batch}_bs{batch_size}.pkl"
        with open(batch_str, 'rb') as f:
            pkl_dict = pkl.load(f)
            x_t_p2d = pkl_dict[dataset_p2d_key]
            f.close()
        # truncate along timeslot axis
        t_i, t_e = t_offset, t_offset+T
        i_s = batch*batch_size
        i_e = i_s + batch_size
        x[i_s:i_e,:,:,:] = x_t[:,t_i:t_e,:,:]
        x_p2d[i_s:i_e,:,:,:] = x_t_p2d[:,t_i:t_e,:,:]
        pow_diff[i_s:i_e,:] = pow_diff_t[:,t_i:t_e]

    # split to train/val
    val_idx = int(x.shape[0]*val_split) 
    x_train = x[:val_idx,:,:,:]
    x_val = x[val_idx:,:,:,:]
    x_train_p2d = x_p2d[:val_idx,:,:,:]
    x_val_p2d = x_p2d[val_idx:,:,:,:]
    out_dict = {
        "x_train": x_train,
        "x_val": x_val,
        "x_train_p2d": x_train_p2d,
        "x_val_p2d": x_val_p2d,
        "pow_diff": pow_diff
    }

    return out_dict
    # return [pow_all, data_train, data_val, x_train_full, x_val_full]

def dataset_pipeline_full(batch_num, batch_offset, debug_flag, aux_bool, dataset_spec, diff_spec, M_1, t_offset=0, img_channels = 2, img_height = 32, img_width = 32, T = 10, train_argv = True, n_truncate=32, mode="full", return_pow=True):
    """
    Load and split dataset according to arguments
    Assumes batch-wise splits (i.e., concatenating along axis=0)
    Assumes dataset_full_key, indicating presence of full CSI matrices 
    mode -> "full" returns non-truncated matrices
         -> "truncate" returns truncated matrices
    Returns: [pow_diff, data_train, data_val]
    """
    print(f"=== dataset_pipeline_full with T={T} timeslots, t_offset={t_offset} ===")

    # x_train = x_val = x_train_full = x_val_full = None
    # x_all = x_all_full = pow_all = None
    x_all = pow_all = None

    assert(len(dataset_spec) == 5)
    dataset_str, dataset_tail, dataset_key, dataset_full_key, val_split = dataset_spec

    assert(mode in ["truncate", "full"])
    target_key = dataset_key if mode == "truncate" else dataset_full_key

    for batch in range(batch_num):
    # for batch in range(1,batch_num+1):
        true_batch = batch + batch_offset
        batch_str = f"{dataset_str}{true_batch}{dataset_tail}"
        print(f"--- Adding batch #{batch} from {batch_str} with key={target_key} ---")
        with h5py.File(batch_str, 'r') as f:
            x_t = np.transpose(f[target_key][()], [3,2,1,0])
            # x_t_full = np.transpose(f[dataset_full_key][()], [3,2,1,0]) if type(dataset_full_key) != type(None) else None
            f.close()
        # def add_batch_full(data, batch, n_delay, n_angle, n_truncate):
        # truncate along timeslot axis
        t_i, t_e = t_offset, t_offset+T
        x_t = x_t[:,t_i:t_e,:,:]
        x_all = add_batch_full(x_all, x_t, img_height, img_width, n_truncate, batch_num, batch)
        # x_all_full = add_batch_full(x_all_full, x_t_full, img_height, img_width, x_t_full.shape[2])

    # split to train/val
    val_idx = int(x_all.shape[0]*val_split) 
    x_train = x_all[:val_idx,:,:,:]
    x_val = x_all[val_idx:,:,:,:]

    data_list = [x_train, x_val]
    data_strs = ["x_train", "x_val"]
    for data_i, str_i in zip(data_list, data_strs):
        print(f"-> {str_i}.shape: {data_i.shape}")

    if aux_bool and mode == "truncate":
        if train_argv:
            aux_train = np.zeros((len(x_train),M_1))
            data_train = [aux_train, x_train]
        aux_val = np.zeros((len(x_val),M_1)).astype('float32')
        data_val = [aux_val, x_val]
    else:
        data_train = x_train
        data_val = x_val

    if return_pow:
        T = x_all.shape[1]
        for timeslot in range(1,T+1):
            print(f"--- Adding pow #{timeslot} using {diff_spec[0]}{timeslot}.mat ---")
            pow_diff, pow_diff_up = load_pow_diff(diff_spec, T=timeslot)
            pow_all = add_batch_pow(pow_all, pow_diff)

        # TODO: get rid of this once we are using all batches
        pow_all = pow_all[:x_all.shape[0]]
    else:
        pow_all = None
    
    return [pow_all, data_train, data_val]
    # return [pow_all, data_train, data_val, x_train_full, x_val_full]

def dataset_pipeline_Kusers(batch_num, batch_offset, dataset_spec, K = 2, img_channels = 2, img_height = 32, img_width = 32, T = 10, train_argv = True, n_truncate=32, mode="full"):
    """
    Load and split dataset according to arguments
    Assumes batch-wise splits (i.e., concatenating along axis=0)
    Assumes full CSI matrices (no truncation)
    Assumes K users for distributed channel estimation/precoding
    mode -> "full" returns non-truncated matrices
         -> "truncate" returns truncated matrices
    Returns: [pow_diff, data_train, data_val]
    """

    # x_train = x_val = x_train_full = x_val_full = None
    # x_all = x_all_full = pow_all = None
    x_all_down = pow_all_down = x_all_up = pow_all_up = None

    assert(len(dataset_spec) == 5)
    dataset_str, dataset_tail, dataset_key_down, dataset_key_up, val_split = dataset_spec

    assert(mode in ["truncate", "full"])
    # target_key = dataset_key if mode == "truncate" else dataset_full_key

    for batch in range(1,batch_num+1):
        down_str = f"{dataset_str}{batch}_down{dataset_tail}"
        print(f"--- Adding batch #{batch} from {down_str} ---")
        mat = sio.loadmat(down_str)
        x_t = mat[dataset_key_down]
        x_t = np.reshape(x_t, (x_t.shape[0], K, T, img_height, img_width))
        x_t = np.fft.ifft(x_t, axis=3)
        up_str = f"{dataset_str}{batch}_up{dataset_tail}"
        print(f"--- Adding batch #{batch} from {up_str} ---")
        mat = sio.loadmat(up_str)
        x_t_u = mat[dataset_key_up]
        x_t_u = np.reshape(x_t_u, (x_t.shape[0], K, T, img_height, img_width))
        x_t_u = np.fft.ifft(x_t_u, axis=3)

        x_all_down = add_batch_full_Kusers(x_all_down, x_t, img_height, img_width, n_truncate)
        x_all_up = add_batch_full_Kusers(x_all_up, x_t_u, img_height, img_width, n_truncate)

    # split to train/val
    val_idx = int(x_all_down.shape[0]*val_split) 
    x_down_train = x_all_down[:val_idx,:]
    x_down_val = x_all_down[val_idx:,:]
    x_up_train = x_all_up[:val_idx,:]
    x_up_val = x_all_up[val_idx:,:]

    data_down_list = [x_down_train, x_down_val]
    data_up_list = [x_up_train, x_up_val]
    data_strs = ["x_train", "x_val"]
    str_link_list = ["downlink", "uplink"]
    for data_list, str_link in zip([data_down_list, data_up_list], str_link_list):
        for data_i, str_i in zip(data_list, data_strs):
            print(f"-> {str_link} - {str_i}.shape: {data_i.shape}")

    # if aux_bool and mode == "truncate":
    #     if train_argv:
    #         aux_down_train = np.zeros((len(x_train),M_1))
    #         data_train = [aux_train, x_train]
    #     aux_val = np.zeros((len(x_val),M_1)).astype('float32')
    #     data_val = [aux_val, x_val]
    # else:
    #     data_train = x_train
    #     data_val = x_val

    # T = x_all_down.shape[2]
    # for batch in range(1,batch_num+1):
    #     print(f"--- Adding pow #{batch} using {diff_spec[0]}{batch}.mat ---")
    #     pow_diff_down, pow_diff_up = load_pow_diff(diff_spec, T=T)
    #     pow_all_down = add_batch_pow(pow_all_down, pow_diff_down, axis=0)
    #     pow_all_up = add_batch_pow(pow_all_up, pow_diff_up, axis=0)

    # # TODO: get rid of this once we are using all batches
    # pow_all = pow_all[:x_all_down.shape[0]]
    return [x_down_train, x_down_val, x_up_train, x_up_val]

def dataset_pipeline(batch_num, debug_flag, aux_bool, dataset_spec, M_1, img_channels = 2, img_height = 32, img_width = 32, data_format = "channels_first", T = 10, train_argv = True,  merge_val_test = True, quant_config = None, idx_split=0, n_truncate=32, total_num_files=21):
    """
    Load and split dataset according to arguments
    Assumes batch-wise splits (i.e., concatenating along axis=0)
    Returns: [data_train, data_val, data_test]
    """
    print(f"aux_bool: {aux_bool}")
    x_train = x_train_up = x_val = x_val_up = x_test = x_test_up = None

    if dataset_spec:
        train_str = dataset_spec[0]
        val_str = dataset_spec[1]
        if len(dataset_spec) ==3:
            test_str = dataset_spec[2]
    else:
        train_str = 'data/data_001/Data100_Htrainin_down_FDD_32ant'
        val_str = 'data/data_001/Data100_Hvalin_down_FDD_32ant'

    for batch in range(batch_num):
        print("--- Adding batch #{} ---".format(batch))
        # mat = sio.loadmat('data/data_001/Data100_Htrainin_down_FDD_32ant_{}.mat'.format(batch))
        if train_argv:
            mat = sio.loadmat(batch_str(train_str,batch))
            x_train  = add_batch(x_train, mat, 'train', T, img_channels, img_height, img_width, data_format, n_truncate)
        mat = sio.loadmat(batch_str(val_str,batch))
        x_val  = add_batch(x_val, mat, 'val', T, img_channels, img_height, img_width, data_format, n_truncate)
        if len(dataset_spec) == 3:
            mat = sio.loadmat(batch_str(test_str,batch))
            x_test  = add_batch(x_test, mat, 'test', T, img_channels, img_height, img_width, data_format, n_truncate)

    if len(dataset_spec) < 3:
        x_test = x_val
        x_test_up = x_val_up

    # bundle training data calls so they are skippable
    if train_argv:
        # x_train = subsample_time(x_train,T)
        x_train = x_train.astype('float32')
        if img_channels > 0:
            x_train = np.reshape(x_train, get_data_shape(len(x_train), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format
        if aux_bool:
            aux_train = np.zeros((len(x_train),M_1))

    # x_val = subsample_time(x_val,T)
    # x_test = subsample_time(x_test,T)

    x_val = x_val.astype('float32')
    x_test = x_test.astype('float32')

    if img_channels > 0:
        x_val = np.reshape(x_val, get_data_shape(len(x_val), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format
        x_test = np.reshape(x_test, get_data_shape(len(x_test), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format

    if aux_bool:
        aux_val = np.zeros((len(x_val),M_1)).astype('float32')
        aux_test = np.zeros((len(x_test),M_1)).astype('float32')

    if (merge_val_test):
        # merge validation and test sets

        if aux_bool:
            aux_val  = np.vstack((aux_val, aux_test))
            aux_test = aux_val
        x_val  = np.vstack((x_val, x_test))
        x_test = x_val

    # concat and (optionally) quantize data
    # TODO: Re-validate. Changed since last run of quantized CSI. 
    quant_bool = type(quant_config) != type(None)
    if quant_bool:
        val_min, val_max, bits = get_keys_from_json(quant_config, keys=['val_min','val_max','bits'])
    if train_argv:
        data_train = x_train if not quant_bool else quantize(x_train,val_min,val_max,bits) 
    data_val = x_val if not quant_bool else quantize(x_val,val_min,val_max,bits) 
    data_test = x_test if not quant_bool else quantize(x_test,val_min,val_max,bits) 
    if aux_bool:
        if train_argv:
            data_train = [aux_train, data_train]
        data_val = [aux_val, data_test]
        data_test = [aux_test, data_test]

    if (not train_argv):
        data_train = None

    # if img_channels > 0:
    #     return data_train[:,:,:n_truncate,:], data_val[:,:,:n_truncate,:], data_test[:,:,:n_truncate,:]
    # else:
    return data_train, data_val, data_test

def dataset_pipeline_complex(debug_flag, aux_bool, dataset_spec, diff_spec, M_1, img_channels = 2, img_height = 32, img_width = 32, data_format = "channels_first", T = 10, train_argv = True, quant_config = None, idx_split=0, n_truncate=32, total_num_files=21, subsample_prop=1.0):
    """
    Load and split dataset according to arguments
    Assumes timeslot splits (i.e., concatenating along axis=1)
    Returns: [data_train, data_val]
    """
    x_all = None
    assert(len(dataset_spec) == 4)
    dataset_str, dataset_tail, dataset_key, val_split = dataset_spec

    for batch in range(1,total_num_files):
        batch_str = f"{dataset_str}{batch}{dataset_tail}"
        print(f"--- Adding batch #{batch} from {batch_str} ---")
        x_t = sio.loadmat(f"{dataset_str}{batch}{dataset_tail}")[dataset_key]
        x_t = np.concatenate((np.expand_dims(np.real(x_t[:,:T,:,:]), axis=2), np.expand_dims(np.imag(x_t[:,:T,:,:]), axis=2)), axis=2)
        print(f"-> batch shape: {x_t.shape}")
        if batch == 1:
            # np.random.seed(1)
            batch_size = x_t.shape[0]
            # rand_idx = np.random.permutation(range(data_size))
            subsample_idx = int(subsample_prop*batch_size) 
        if subsample_prop < 1.0:
            x_t = x_t[(batch-1)*subsample_idx:batch*subsample_idx,:,:,:]
            # x_t = x_t[rand_idx[(batch-1)*subsample_idx:batch*subsample_idx],:,:,:]
            # pow_diff = pow_diff[(batch-1)*subsample_idx:batch*subsample_idx]
        x_all = add_batch_complex(x_all, x_t, n_truncate)

        # pow_all = add_batch_pow(pow_all, pow_diff)

    # split to train/val
    val_idx = int(x_all.shape[0]*val_split) 
    x_train = x_all[:val_idx,:,:,:,:]
    x_val = x_all[val_idx:,:,:,:,:]
    # pow_val = pow_all[val_idx:,:,:]

    # bundle training data calls so they are skippable
    if train_argv:
        # x_train = subsample_time(x_train,T)
        x_train = x_train.astype('float32')
        if img_channels > 0:
            x_train = np.reshape(x_train, get_data_shape(len(x_train), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format
        if aux_bool:
            aux_train = np.zeros((len(x_train),M_1))

    x_val = x_val.astype('float32')

    if img_channels > 0:
        x_val = np.reshape(x_val, get_data_shape(len(x_val), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format

    if aux_bool:
        aux_val = np.zeros((len(x_val),M_1)).astype('float32')

    # concat and (optionally) quantize data
    # TODO: Re-validate. Changed since last run of quantized CSI. 
    quant_bool = type(quant_config) != type(None)
    if quant_bool:
        val_min, val_max, bits = get_keys_from_json(quant_config, keys=['val_min','val_max','bits'])
    if train_argv:
        data_train = x_train if not quant_bool else quantize(x_train,val_min,val_max,bits) 

    data_val = x_val if not quant_bool else quantize(x_val,val_min,val_max,bits) 
    if aux_bool:
        if train_argv:
            data_train = [aux_train, data_train]
        data_val = [aux_val, data_val]

    if (not train_argv):
        data_train = None

    # if img_channels > 0:
    #     return data_train[:,:,:n_truncate,:], data_val[:,:,:n_truncate,:], data_test[:,:,:n_truncate,:]
    # else:
    return data_train, data_val

def dataset_pipeline_col(debug_flag, aux_bool, dataset_spec, diff_spec, M_1, img_channels = 2, img_height = 32, img_width = 32, data_format = "channels_first", T = 10, train_argv = True, quant_config = None, idx_split=0, n_truncate=32, total_num_files=21, subsample_prop=1.0, thresh_idx_path=False, stride=1, mat_type=0):
    """
    Load and split dataset according to arguments
    Assumes timeslot splits (i.e., concatenating along axis=1)
    Returns: [pow_diff, data_train, data_val]
    """
    x_all = pow_all = None
    x_all_up = pow_all_up = None
    if(len(dataset_spec) == 4):
        dataset_str, dataset_tail, dataset_key, val_split = dataset_spec
        dataset_key_up = None
    elif(len(dataset_spec) == 5):
        dataset_str, dataset_tail, dataset_key, dataset_key_up, val_split = dataset_spec

    if thresh_idx_path != False:
        H_thresh_idx = np.squeeze(sio.loadmat(f"{thresh_idx_path}")["i_percent"]) - 1 # subtract one from matlab idx
        print(f"H_thresh_idx.shape: {H_thresh_idx.shape}\nH_thresh_idx: {H_thresh_idx}")

    for timeslot in range(1,T*stride+1,stride):
        batch_str = f"{dataset_str}{timeslot}_{dataset_tail}"
        print(f"--- Adding batch #{timeslot} from {batch_str} ---")
        if mat_type == 0:
            with h5py.File(batch_str, 'r') as f:
                x_t = np.transpose(f[dataset_key][()], [3,2,1,0])
                x_t_up = np.transpose(f[dataset_key_up][()], [3,2,1,0]) if type(dataset_key_up) != type(None) else None
                f.close()
        elif mat_type == 1:
            mat = sio.loadmat(batch_str)
            x_t = mat[dataset_key]
            x_t_up = mat[dataset_key_up]
            x_t = np.reshape(x_t, (x_t.shape[0], img_channels, img_height, img_width))
            x_t_up = np.reshape(x_t_up, (x_t_up.shape[0], img_channels, img_height, img_width))
        # x_val  = add_batch(x_val, mat, 'val', T, img_channels, img_height, img_width, data_format, n_truncate)
        # x_t = sio.loadmat(f"{dataset_str}{timeslot}_{dataset_tail}")[dataset_key]
        if len(diff_spec) > 0:
            pow_diff, pow_diff_up = load_pow_diff(diff_spec, T=timeslot)
        if timeslot == 1:
            # np.random.seed(1)
            data_size = x_t.shape[0] if thresh_idx_path == False else H_thresh_idx.shape[0]
            # rand_idx = np.random.permutation(range(data_size))
            subsample_idx = int(subsample_prop*data_size) 
        if thresh_idx_path != False:
            x_t = x_t[H_thresh_idx]
            x_t_up = x_t_up[H_thresh_idx] if type(dataset_key_up) != type(None) else None
            pow_diff = pow_diff[H_thresh_idx] 
            pow_diff_up = pow_diff_up[H_thresh_idx] if type(dataset_key_up) != type(None) else None
        if subsample_prop < 1.0:
            x_t = x_t[(timeslot-1)*subsample_idx:timeslot*subsample_idx,:,:,:]
            x_t_up = x_t_up[(timeslot-1)*subsample_idx:timeslot*subsample_idx,:,:,:] if type(dataset_key_up) != type(None) else None
            pow_diff = pow_diff[(timeslot-1)*subsample_idx:timeslot*subsample_idx]
            pow_diff_up = pow_diff_up[(timeslot-1)*subsample_idx:timeslot*subsample_idx] if type(dataset_key_up) != type(None) else None
            # x_t = x_t[rand_idx[(timeslot-1)*subsample_idx:timeslot*subsample_idx],:,:,:]
            # pow_diff = pow_diff[rand_idx[(timeslot-1)*subsample_idx:timeslot*subsample_idx]]
        x_all = add_batch_col(x_all, x_t, img_channels, img_height, img_width, data_format, n_truncate)
        x_all_up = add_batch_col(x_all_up, x_t_up, img_channels, img_height, img_width, data_format, n_truncate) if type(dataset_key_up) != type(None) else None

        if len(diff_spec) > 0:
            pow_all = add_batch_pow(pow_all, pow_diff)
            pow_all_up = add_batch_pow(pow_all_up, pow_diff_up) if type(dataset_key_up) != type(None) else None

    # split to train/val
    val_idx = int(x_all.shape[0]*val_split) 
    x_train = x_all[:val_idx,:,:,:,:]
    x_val = x_all[val_idx:,:,:,:,:]
    if type(dataset_key_up) != type(None):
        x_train_up = x_all_up[:val_idx,:,:,:,:] 
        x_val_up = x_all_up[val_idx:,:,:,:,:] 

    # pow_val = pow_all[val_idx:,:,:]

    # bundle training data calls so they are skippable
    if train_argv:
        # x_train = subsample_time(x_train,T)
        x_train = x_train.astype('float32')
        x_train_up = x_train_up.astype('float32') if type(dataset_key_up) != type(None) else None
        if img_channels > 0:
            x_train = np.reshape(x_train, get_data_shape(len(x_train), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format
            x_train_up = np.reshape(x_train_up, get_data_shape(len(x_train), T, img_channels, img_height, n_truncate, data_format)) if type(dataset_key_up) != type(None) else None # adapt this if using `channels_first` image data format
        if aux_bool:
            aux_train = np.zeros((len(x_train),M_1))

    x_val = x_val.astype('float32')
    x_val_up = x_val_up.astype('float32') if type(dataset_key_up) != type(None) else None

    if img_channels > 0:
        x_val = np.reshape(x_val, get_data_shape(len(x_val), T, img_channels, img_height, n_truncate, data_format))  # adapt this if using `channels_first` image data format
        x_val_up = np.reshape(x_val_up, get_data_shape(len(x_val_up), T, img_channels, img_height, n_truncate, data_format)) if type(dataset_key_up) != type(None) else None  # adapt this if using `channels_first` image data format
    if aux_bool:
        aux_val = np.zeros((len(x_val),M_1)).astype('float32')

    # concat and (optionally) quantize data
    # TODO: Re-validate. Changed since last run of quantized CSI. 
    quant_bool = type(quant_config) != type(None)
    if quant_bool:
        val_min, val_max, bits = get_keys_from_json(quant_config, keys=['val_min','val_max','bits'])
    if train_argv:
        data_train = x_train if not quant_bool else quantize(x_train,val_min,val_max,bits) 
        data_train_up = x_train_up if not quant_bool else quantize(x_train,val_min,val_max,bits) 

    data_val = x_val if not quant_bool else quantize(x_val,val_min,val_max,bits) 
    data_val_up = x_val_up if not quant_bool else quantize(x_val,val_min,val_max,bits) 
    if aux_bool:
        if train_argv:
            data_train = [aux_train, data_train]
            data_train_up = [aux_train, data_train_up]
        data_val = [aux_val, data_val]
        data_val_up = [aux_val, data_val_up]

    if (not train_argv):
        data_train = None
        data_train_up = None

    # if img_channels > 0:
    #     return data_train[:,:,:n_truncate,:], data_val[:,:,:n_truncate,:], data_test[:,:,:n_truncate,:]
    # else:
    if len(diff_spec) == 0:
        pow_diff_all = pow_all = None
    if type(dataset_key_up) != type(None):
        return pow_all, data_train, data_val, pow_all_up, data_train_up, data_val_up
    else:
        return pow_all, data_train, data_val

def add_batch_col(dataset, batch, img_channels, img_height, img_width, data_format, n_truncate):
    # concatenate batch data along time axis 
    # Inputs:
    # -> dataset = np.array for downlink
    # -> batch = mat file to add to np.array
    batch = np.expand_dims(batch, axis=1)
    if dataset is None:
        # return batch[:,:,:,:n_truncate] if img_channels > 0 else truncate_flattened_matrix(batch, img_height, img_width, n_truncate)
        return batch[:,:,:n_truncate,:] 
    else:
        # return np.concatenate((dataset, batch[:,:,:,:,:n_truncate]), axis=1) if img_channels > 0 else np.concatenate((dataset,truncate_flattened_matrix(batch, img_height, img_width, n_truncate)), axis=1)
        return np.concatenate((dataset, batch[:,:,:,:n_truncate,:]), axis=1) 

def add_batch_full(data, batch, n_delay, n_angle, n_truncate, batch_num, batch_idx):
    # concatenate batch data onto end of data
    # data/batch shape is (n_batch, T, n_delay, n_angle)
    # Inputs:
    # -> data = np.array for downlink
    # -> batch = mat file to add to np.array
    batch_size = batch.shape[0]
    if data is None: 
        data_shape = (batch_size*batch_num,)+batch.shape[1:]
        data = np.zeros(data_shape, dtype=batch.dtype) # preallocate data
    idx_s = batch_idx * batch_size
    idx_e = idx_s + batch_size
    data[idx_s:idx_e,:] = batch
    return data
        # return batch[:,:,:n_truncate,:] 
    # else:
        # return np.vstack((data,batch[:,:,:n_truncate,:])) 

def add_batch_full_Kusers(data, batch, n_delay, n_angle, n_truncate):
    # concatenate batch data onto end of data
    # data/batch shape is (n_batch, T, n_delay, n_angle)
    # Inputs:
    # -> data = np.array for downlink
    # -> batch = mat file to add to np.array
    if data is None:
        return batch[:,:,:,:n_truncate,:] 
    else:
        return np.vstack((data,batch[:,:,:,:n_truncate,:])) 

def add_batch_pow(dataset, batch, concat_axis=1):
    # concatenate batch data along time axis 
    # Inputs:
    # -> dataset = np.array for downlink
    # -> batch = mat file to add to np.array
    # -> concat_axis = concatenation axis; only use if > 0
    if concat_axis != 0:
        batch = np.expand_dims(batch, axis=concat_axis)
    if dataset is None:
        return batch
    else:
        return np.concatenate((dataset, batch), axis=concat_axis) 

def load_pow_diff(diff_spec,T=1):
    # TODO: load data for T > 1
    # re: magic numbers -- matfiles have __header__, __version__, and __global__ keys
    # we skip i in [0,1,2] when processing the loaded mat_dict
    mat_dict = sio.loadmat(f"{diff_spec[0]}{T}.mat")
    for i, (key, val) in enumerate(mat_dict.items()):
        if i == 3: # magic number
            pow_diff_down = mat_dict[key]
            pow_diff_up = None
        if i == 4: # magic number
            pow_diff_up = mat_dict[key]
    return [pow_diff_down, None] if type(pow_diff_up) == type(None) else [pow_diff_down, pow_diff_up]

def add_batch_complex(data_down, batch, n_truncate):
    # concatenate batch data onto end of data
    # Inputs:
    # -> data_up = np.array for uplink
    # -> data_down = np.array for downlink
    # -> batch = mat file to add to np.array
    # -> type_str = part of key to select for training/validation
    if data_down is None:
        return batch[:,:,:,:n_truncate,:] 
    else:
        return np.vstack((data_down,batch[:,:,:,:n_truncate,:])) 
