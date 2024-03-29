import sys
import copy
import torch
import pickle
import numpy as np
from tqdm import tqdm
from torch import nn, optim, autograd

sys.path.append("/home/mdelrosa/git/brat")
from utils.NMSE_performance import get_NMSE, denorm_H3, denorm_H4, denorm_sphH4, denorm_sph_magH3, denorm_magH3
from utils.data_tools import dataset_pipeline, subsample_batches, split_complex, load_pow_diff
from utils.unpack_json import get_keys_from_json

from prettytable import PrettyTable

def count_parameters(model):
    """
    count trainable params in model
    from Vlad Rusu's SO answer: https://stackoverflow.com/a/62508086 """
    table = PrettyTable(["Modules", "Parameters"])
    total_params = 0
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad: continue
        param = parameter.numel()
        table.add_row([name, param])
        total_params+=param
    print(table)
    print(f"Total Trainable Params: {total_params}")
    return total_params

def fit(model, train_ldr, valid_ldr, batch_num, schedule=None, criterion=nn.MSELoss(), epochs=10, timers=None, json_config=None, debug_flag=True, pickle_dir=".", input_type="split", patience=5000, network_name=None):
    # pull out timers
    fit_timer = timers["fit_timer"] 

    # load hyperparms
    network_name = get_keys_from_json(json_config, keys=["network_name"])[0] if network_name == None else network_name

    # criterion = nn.MSELoss()
    # TODO: if we use lr_schedule, then do we need to use SGD instead? 
    lr = get_keys_from_json(json_config, keys=['learning_rate'])[0] if schedule == None else 1
    # optimizer = optim.SGD(model.parameters(), lr=lr)
    # if schedule != None:
    #     lr_lambda = lambda epoch: schedule.get_param(epoch) 
    #     lr_scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, [lr_lambda], verbose=True)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    # TODO: Load in epoch
    checkpoint = {
                    "latest_model": None,
                    "latest_epoch": None,
                    "best_model": None,
                    "best_epoch": 0,
                    "best_mse": None,
                    "best_nmse": None,
                    # "optimizer_state": None,
    }

    history = {
                    "train_loss": np.zeros(epochs),
                    "test_loss": np.zeros(epochs)
                }
    l = None
    best_test_loss = None
    epochs_no_improvement = 0
    # grace_period = 1000
    # anneal_range = [0.0, 1.0]
    # beta_annealer = AnnealingSchedule(anneal_range, epoch_limit=grace_period)
    # clip_val = 1e5 # tuning this

    with fit_timer:
        for epoch in range(epochs):
            train_loss = 0
            model.training = True
            # for i, data_batch in enumerate(tqdm(train_ldr, desc=f"Epoch #{epoch+1}"), 0):
            for i, data_tuple in enumerate(tqdm(train_ldr, desc=f"Epoch #{epoch+1}"), 0):
                # inputs = autograd.Variable(data_batch).float()
                # print(f"len(data_tuple): {len(data_tuple)}")
                if len(data_tuple) != 2:
                    data_batch = data_tuple
                # elif len(data_tuple) == 2:
                else:
                    aux_batch, data_batch = data_tuple
                    aux_input = autograd.Variable(aux_batch)
                h_input = autograd.Variable(data_batch)
                optimizer.zero_grad()
                model_in = h_input if len(data_tuple) != 2 else [aux_input, h_input]
                dec = model(model_in)
                mse = criterion(dec, h_input[:,1,:,:].unsqueeze(1)) #TODO: remove indices; is this compatible with other models? (CsiNetPro?)
                train_loss += mse
                mse.backward()
                # torch.nn.utils.clip_grad_norm_(model.parameters(), clip_val) # clip
                optimizer.step()
                # l = loss.data[0]
                # l = loss
                # print(f"loss.data: {loss.data} -- type(loss): {type(loss)}")
                if (i != 0):
                    tqdm.write(f"\033[A                                                         \033[A")
                tqdm_str = f"Epoch #{epoch+1}/{epochs}: Training loss: {mse.data:.5E}"
                tqdm.write(tqdm_str)
            # post training step, dump to checkpoint
            checkpoint["model"] = copy.deepcopy(model).to("cpu").state_dict()
            optimizer_state = copy.deepcopy(optimizer.state_dict())
            checkpoint["latest_epoch"] = epoch
            history["train_loss"][epoch] = train_loss.detach().to("cpu").numpy() / (i+1)

            # validation step
            # model.training = False # optionally check just the MSE performance during eval
            with torch.no_grad():
                test_loss = 0
                # for i, data_batch in enumerate(valid_ldr):
                for i, data_tuple in enumerate(valid_ldr):
                    # inputs = autograd.Variable(data_batch).float()
                    if len(data_tuple) != 2:
                        data_batch = data_tuple
                    # elif len(data_tuple) == 2:
                    else:
                        aux_batch, data_batch = data_tuple
                        aux_input = autograd.Variable(aux_batch)
                    h_input = autograd.Variable(data_batch)
                    optimizer.zero_grad()
                    model_in = h_input if len(data_tuple) != 2 else [aux_input, h_input]
                    dec = model(model_in)
                    mse = criterion(dec, h_input[:,1,:,:].unsqueeze(1))
                    test_loss += mse
                history["test_loss"][epoch] = test_loss.detach().to("cpu").numpy() / (i+1)
                # if epoch >= grace_period:
                if type(best_test_loss) == type(None) or best_test_loss > history["test_loss"][epoch]:
                    best_test_loss = history["test_loss"][epoch]
                    checkpoint["best_epoch"] = epoch
                    checkpoint["best_model"] = copy.deepcopy(model).to("cpu").state_dict()
                    epochs_no_improvement = 0
                    if not debug_flag:
                        torch.save(checkpoint["best_model"], f"{pickle_dir}/{network_name}-best-model.pt")
                    print(f"Epoch #{epoch+1}/{epochs}: Test loss: {history['test_loss'][epoch]:.5E} -- New best epoch: {epoch+1}")
                elif epochs_no_improvement < patience:
                    epochs_no_improvement += 1
                    print(f"Epoch #{epoch+1}/{epochs}: Test loss: {history['test_loss'][epoch]:.5E} -- Test loss did not improve. Best epoch: #{checkpoint['best_epoch']+1}")
                else:
                    model.load_state_dict(checkpoint["best_model"])
                    if not debug_flag:
                        torch.save(checkpoint["best_model"], f"{pickle_dir}/{network_name}-best-model.pt")
                    print(f"Epoch #{epoch+1}/{epochs}: Test loss: {history['test_loss'][epoch]:.5E} -- Test loss did not improve for {patience} epochs. Loading best epoch #{checkpoint['best_epoch']+1}")
                    break
                # else:
                #     # don't track best epoch until grace period has expired
                #     print(f"Epoch #{epoch+1}/{epochs}: Test loss: {history['test_loss'][epoch]:.5E}. Grace period is {grace_period} epochs.")
                checkpoint["latest_model"] = copy.deepcopy(model).to("cpu").state_dict()
                tqdm.write(f"Epoch #{epoch+1}/{epochs}: Training loss: {history['train_loss'][epoch]:.5E} -- Test loss: {history['test_loss'][epoch]:.5E}")

                if schedule != None:
                    lr_scheduler.step()
                    print(lr_scheduler.state_dict())

    return [model, checkpoint, history, optimizer, timers]

def score(model, valid_ldr, data_val, batch_num, checkpoint, history, optimizer, timeslot=0, err_dict=None, timers=None, json_config=None, debug_flag=True, str_mod="", torch_type=torch.float, n_train=0, pow_diff_t=None, data_phase=None, thresh_idx_path=False):
    """
    take model, predict on valid_ldr, score
    currently scores a spherically normalized dataset
    """

    # pull out timers
    predict_timer = timers["predict_timer"]
    score_timer = timers["score_timer"]

    batch_size, minmax_file, norm_range = get_keys_from_json(json_config, keys=["batch_size", "minmax_file", "norm_range"])

    with predict_timer:
        # y_hat = torch.zeros(data_val.shape).to(device)
        # y_test = torch.zeros(data_val.shape).to(device)
        model.training = False
        model.eval()
        with torch.no_grad():
            y_hat = torch.zeros(data_val.shape, dtype=torch_type).to("cpu")
            y_test = torch.zeros(data_val.shape, dtype=torch_type).to("cpu")
            for i, data_tuple in enumerate(valid_ldr):
                # inputs = autograd.Variable(data_batch).float()
                if len(data_tuple) != 2:
                    data_batch = data_tuple
                # elif len(data_tuple) == 2:
                else:
                    aux_batch, data_batch = data_tuple
                    aux_input = autograd.Variable(aux_batch)
                h_input = autograd.Variable(data_batch)
                model_in = h_input if len(data_tuple) != 2 else [aux_input, h_input]
            # for i, data_batch in enumerate(valid_ldr):
            #     # inputs = autograd.Variable(data_batch).float()
            #     inputs = autograd.Variable(data_batch)
                optimizer.zero_grad()
                idx_s = i*batch_size
                idx_e = min((i+1)*batch_size, y_hat.shape[0])
                temp = model(model_in)
                y_hat[idx_s:idx_e,:,:,:] = model(model_in).to("cpu")
                y_test[idx_s:idx_e,:,:,:] = h_input[:,1,:,:].unsqueeze(1).to("cpu")

    # for markovnet, we add "addend" to the error to get our actual estimates
    if type(err_dict) != type(None):            
        print("--- err_dict passed in - calculating estimates with error added back --- ")
        if type(err_dict["M"]) == type(3.14): # float
            y_hat = y_hat * err_dict["M"] + err_dict["hat"]
            y_test = y_test * err_dict["M"] + err_dict["hat"]
        elif len(err_dict["M"]) == 2: # list with min/max
            # in this case, y_hat/y_test are error magnitude estimate/ground truth
            print(f"--- pre-denorm: E_hat range: {np.min(y_hat.detach().numpy()):4.3E} to {np.max(y_hat.detach().numpy()):4.3E} ---")
            print(f"--- pre-denorm: E_test range: {np.min(y_test.detach().numpy()):4.3E} to {np.max(y_test.detach().numpy()):4.3E} ---")
            E_hat = y_hat[:,0,:,:] * (err_dict["M"][1] - err_dict["M"][0]) + err_dict["M"][0] # denorm error
            E_test = y_test[:,0,:,:] * (err_dict["M"][1] - err_dict["M"][0]) + err_dict["M"][0] # denorm error
            print(f"--- post-denorm: E_hat range: {np.min(E_hat.detach().numpy()):4.3E} to {np.max(E_hat.detach().numpy()):4.3E} ---")
            print(f"--- post-denorm: E_test range: {np.min(E_test.detach().numpy()):4.3E} to {np.max(E_test.detach().numpy()):4.3E} ---")
            y_hat = E_hat + err_dict["hat"][:,0,:,:] # add error term back; hat magnitude
            y_test = E_test + err_dict["hat"][:,0,:,:] # add error term back; test magnitude
            y_hat = torch.from_numpy(np.expand_dims(y_hat, axis=1)).to("cpu")
            y_test = torch.from_numpy(np.expand_dims(y_test, axis=1)).to("cpu")
            data_phase = [None, None]
            data_phase[0] = err_dict["data_phase"][0] + np.expand_dims(err_dict["gt"][:,1,:,:], axis=1)
            data_phase[1] = err_dict["data_phase"][1] + np.expand_dims(err_dict["hat"][:,1,:,:], axis=1)

    # score model - account for spherical normalization
    with score_timer:
        # if y_hat.shape[1] == 1:
        #     y_hat = torch.cat((y_hat.real, y_hat.imag), 1)
        #     y_test = torch.cat((y_test.real, y_test.imag), 1)
        print(f"y_hat.shape: {y_hat.shape} - y_test.shape: {y_test.shape} - data_phase[0].shape: {data_phase[0].shape} - data_phase[1].shape: {data_phase[1].shape}")    
        if norm_range in ["norm_sph_magH3", "norm_magH3"]:
            y_hat = y_hat[:,0,:,:].unsqueeze(1)
            y_test = y_test[:,0,:,:].unsqueeze(1)
        print('-> pre denorm: y_hat range is from {} to {}'.format(np.min(y_hat.detach().numpy()), np.max(y_hat.detach().numpy())))
        print('-> pre denorm: y_test range is from {} to {}'.format(np.min(y_test.detach().numpy()),np.max(y_test.detach().numpy())))
        if norm_range == "norm_H3":
            y_hat_denorm = denorm_H3(y_hat.detach().numpy(),minmax_file)
            y_test_denorm = denorm_H3(y_test.detach().numpy(),minmax_file)
        elif norm_range == "norm_H4":
            y_hat_denorm = denorm_H4(y_hat.to("cpu").detach().numpy(),minmax_file)
            y_test_denorm = denorm_H4(y_test.to("cpu").detach().numpy(),minmax_file)
        elif norm_range == "norm_sphH4":
            t1_power_file = get_keys_from_json(json_config, keys=["t1_power_file"])[0]
            y_hat_denorm = denorm_sphH4(y_hat.detach().numpy(),minmax_file, t1_power_file, batch_num, timeslot=timeslot, thresh_idx_path=thresh_idx_path)
            y_test_denorm = denorm_sphH4(y_test.detach().numpy(),minmax_file, t1_power_file, batch_num, timeslot=timeslot, thresh_idx_path=thresh_idx_path)
        elif norm_range == "norm_sph_magH3":
            assert(type(data_phase) != type(None))
            t1_power_file = get_keys_from_json(json_config, keys=["t1_power_file"])[0]
            y_test = np.concatenate((y_test.detach().numpy(), data_phase[0]), axis=1)
            y_test_denorm = denorm_sph_magH3(y_test,minmax_file, t1_power_file, batch_num, timeslot=timeslot)
            y_hat = np.concatenate((y_hat.detach().numpy(), data_phase[1]), axis=1)
            y_hat_denorm = denorm_sph_magH3(y_hat,minmax_file, t1_power_file, batch_num, timeslot=timeslot)
            # y_hat = np.concatenate((np.expand_dims(y_hat[:,0,:,:], axis=1), data_phase[0]), axis=1) # return hat with non-quantized phase
        elif norm_range == "norm_magH3":
            y_test = np.concatenate((y_test.detach().numpy(), data_phase[0]), axis=1)
            y_test_denorm = denorm_magH3(y_test, minmax_file, timeslot=timeslot)
            y_hat = np.concatenate((y_hat.detach().numpy(), data_phase[1]), axis=1)
            y_hat_denorm = denorm_magH3(y_hat, minmax_file, timeslot=timeslot)
        # predicted on pooled data -- split out validation set
        print('-> post denorm: y_hat range is from {} to {}'.format(np.min(y_hat_denorm),np.max(y_hat_denorm)))
        print('-> post denorm: y_test range is from {} to {}'.format(np.min(y_test_denorm),np.max(y_test_denorm)))
        y_test_denorm, y_hat_denorm = y_test_denorm[n_train:,:,:,:], y_hat_denorm[n_train:,:,:,:]
        print('-> post split: y_hat range is from {} to {}'.format(np.min(y_hat_denorm),np.max(y_hat_denorm)))
        print('-> post split: y_test range is from {} to {}'.format(np.min(y_test_denorm),np.max(y_test_denorm)))
        y_hat_denorm = y_hat_denorm[:,0,:,:] + 1j*y_hat_denorm[:,1,:,:]
        y_test_denorm = y_test_denorm[:,0,:,:] + 1j*y_test_denorm[:,1,:,:]
        y_shape = y_test_denorm.shape
        mse, nmse = get_NMSE(y_hat_denorm, y_test_denorm, return_mse=True, n_ang=y_shape[1], n_del=y_shape[2]) # one-step prediction -> estimate of single timeslot
        print(f"-> {str_mod} - truncate | NMSE = {nmse:5.3f} | MSE = {mse:.4E}")
        checkpoint["best_nmse"] = nmse
        checkpoint["best_mse"] = mse

        if type(pow_diff_t) != type(None): 
            mse, nmse = get_NMSE(y_hat_denorm, y_test_denorm, return_mse=True, n_ang=y_shape[1], n_del=y_shape[2], pow_diff_timeslot=pow_diff_t[n_train:]) # one-step prediction -> estimate of single timeslot
            print(f"-> {str_mod} - all | NMSE = {nmse:5.3f} | MSE = {mse:.4E}")
            checkpoint["best_nmse_full"] = nmse
            checkpoint["best_mse_full"] = mse

    return [checkpoint, y_hat, y_test]

def save_predictions(model, ldr, data, optimizer, timers, err_dict=None, json_config=None, dir=".", split="train"):
    """
    make predictions with model; pickle to specified location
    """
    # pull out timers
    predict_timer = timers["predict_timer"]
    batch_size, network_name, base_pickle = get_keys_from_json(json_config, keys=["batch_size", "network_name", "base_pickle"])

    # make predictions, y_hat
    with predict_timer:
        # y_hat = torch.zeros(data_val.shape).to(device)
        # y_test = torch.zeros(data_val.shape).to(device)
        model.training = False
        model.eval()
        with torch.no_grad():
            y_hat = torch.zeros(data.shape).to("cpu")
            y_gt = torch.zeros(data.shape).to("cpu")
            for i, data_batch in enumerate(ldr):
                inputs = autograd.Variable(data_batch)
                optimizer.zero_grad()
                idx_s = i*batch_size
                idx_e = min((i+1)*batch_size, y_hat.shape[0])
                y_hat[idx_s:idx_e,:,:,:] = model(inputs).to("cpu")
                y_gt[idx_s:idx_e,:,:,:] = inputs.to("cpu")

    # for markovnet, we add "addend" to the error to get our actual estimates
    if type(err_dict) != type(None):            
        y_hat = y_hat * err_dict["M"] + err_dict["hat"]
        y_gt = y_gt * err_dict["M"] + err_dict["hat"]

    print(f"--- In save_predictions: y_hat.shape: {y_hat.shape} - y_gt.shape: {y_gt.shape} ---")
    # save y_hat to target dir
    pickle_file = "{}/{}-predictions-{}.pkl".format(dir,network_name,split)
    with open(pickle_file, "wb") as f:
        pickle.dump(y_hat, f)
        f.close()

    # save y_gt to target dir
    pickle_file = "{}/{}-ground-truth-{}.pkl".format(dir,network_name,split)
    with open(pickle_file, "wb") as f:
        pickle.dump(y_gt, f)
        f.close()

def save_checkpoint_history(checkpoint, history, optimizer, dir=".", network_name="network_name"):
    # save checkpoint, history, optimizer from training
    optimizer_state = copy.deepcopy(optimizer.state_dict())
    for filename, target in [("checkpoint", checkpoint), ("history", history)]:
        pickle_file = "{}/{}-{}.pkl".format(dir,network_name,filename)
        with open(pickle_file, "wb") as f:
            pickle.dump(target, f)
            f.close()
    torch.save(optimizer_state, "{}/{}-optimizer.pt".format(dir,network_name))
    torch.save(checkpoint["latest_model"], "{}/{}-model.pt".format(dir,network_name))

def save_scheduler(scheduler, dir=".", network_name="network_name"):
    scheduler_state = copy.deepcopy(scheduler.state_dict())
    torch.save(scheduler_state, "{}/{}-scheduler.pt".format(dir,network_name))

def load_checkpoint_history(dir, model, optimizer_obj=optim.Adam, network_name="network_name"):
    # save checkpoint, history, optimizer from training
    optimizer = optimizer_obj(model.parameters())
    pickle_objects = {}
    for filename, extension in [("checkpoint", ".pkl"), ("history", ".pkl"), ("optimizer", ".pt")]:
        pickle_file = "{}/{}-{}{}".format(dir,network_name,filename,extension)
        if extension == ".pkl":
            with open(pickle_file, "rb") as f:
                pickle_objects[filename] = pickle.load(f)
                f.close()
        elif extension == ".pt":
            pickle_objects[filename] = torch.load(pickle_file)
    checkpoint, history, optimizer_state = pickle_objects["checkpoint"], pickle_objects["history"], pickle_objects["optimizer"]
    optimizer.load_state_dict(optimizer_state)
    model = model.load_state_dict(checkpoint["best_model"])
    return [model, checkpoint, history, optimizer]