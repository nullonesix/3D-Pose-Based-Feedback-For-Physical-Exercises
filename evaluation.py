import pickle, os
import torch
import numpy as np
import pandas as pd

from torch.utils.data import DataLoader
from models import *
from utils import display_poses, get_labels, test_class_v4, idct_2d, test_corr_v4, dct_2d

# torch.cuda.set_device(2)
# print('GPU Index: {}'.format(torch.cuda.current_device()))


def get_full_label(raw_labels):
    map_label = {1: 'Correct', 2: 'Feets too wide', 3: 'Knees inward', 4: 'Not low enough', 5: 'Front bended',
                 6: 'Knees pass toes', 7: 'Banana back', 8: 'Rolled back', 9: 'Asymmetric', 10: 'Unknown'}
    acts = [tup[0] for tup in raw_labels]
    full_labels = [map_label[tup[2]] for tup in raw_labels]
    return acts, full_labels


def main_eval(time, opt, data_test, separated=False, model_version=''):

    is_cuda = torch.cuda.is_available()
    use_random_one_hot = False

    test_loader = DataLoader(dataset=data_test, batch_size=len(data_test))
    
    savepath = opt.ckpt + '/result/'

    # Models
    if separated:
        """For separated model"""
        model_corr_path = opt.model_dir
        model_class_path='pretrained_weights/classifer_for_eval.pt'

        # Create models
        model_corr = GCN_corr(hidden_feature=opt.hidden)
        model_class = GCN_corr_class_ours(hidden_feature=256, p_dropout=opt.dropout, classes=12).cuda()   #  best classifier 
        
        # Load parameters
        model_corr.load_state_dict(torch.load(model_corr_path, map_location='cuda:0'))
        model_class.load_state_dict(torch.load(model_class_path, map_location='cuda:0'))

        model_id = model_corr_path[-19:-3] if model_corr_path[0] != 'p' else 'pretrained'
        if is_cuda:
            model_class.cuda()
            model_class.eval()
            model_corr.cuda()
            model_corr.eval()
    else: 
        """For combined model"""
        model = GCN_corr_class(hidden_feature=opt.hidden) if model_version == 'Combined_wo_Feedback' else GCN_corr_class_ours(hidden_feature=opt.hidden)
        model_path = opt.model_dir
        # import pdb; pdb.set_trace()
        # model.load_state_dict(torch.load(model_path))
        model.load_state_dict(torch.load(opt.model_dir, map_location='cuda:0'))

        model_id = model_path[-19:-3] if model_path[0] != 'p' else 'pretrained'

        if is_cuda:
            model.cuda()
            model.eval()

    # Evaluation
    with torch.no_grad():
        for i, (batch_id, inputs) in enumerate(test_loader):
            if is_cuda:
                inputs = inputs.cuda().float()
            else:
                inputs = inputs.float()

            labels = get_labels([test_loader.dataset.inputs_label[int(i)] for i in batch_id], level=1)
            if separated:
                _, pred_in = torch.max(model_class(inputs, labels, False)[2].data, 1)
                deltas, att = model_corr(inputs)
                _, pred_out = torch.max(model_class(inputs+deltas, labels, False)[2].data, 1)
            else:
                if model_version=='Ours':
                    deltas, _, y_pred = model(inputs, labels, Use_label=False,random_one_hot=use_random_one_hot)
                    _, pred_in = torch.max(y_pred.data, 1)  
                   
                    outputs = inputs+deltas
                    _, pred_out = torch.max(model(outputs, labels, Use_label=False, random_one_hot=use_random_one_hot)[2].data, 1)
                    
                    ''' Visulization '''
                    # whether_plot = input('Do you wanna plot the results?\n(y/n)')
                    whether_plot = 'n'
                    if whether_plot == 'y':
                        inputs_raw = [test_loader.dataset.inputs_raw[int(i)] for i in batch_id]
                        targets_raw = [test_loader.dataset.targets[int(i)] for i in batch_id]

                        for i, o in enumerate(inputs_raw):
                            length = o.shape[1]
                            org_raw = torch.from_numpy(o).T*3000
                            targ_raw = torch.from_numpy(targets_raw[i]).T*3000
                            label = labels[i]

                            if length > outputs[i].shape[1]:
                                m = torch.nn.ZeroPad2d((0, length - deltas[i].shape[1], 0, 0))
                                # delt = dct.idct_2d(m(deltas[i]).T.unsqueeze(0))
                                outputs_raw = idct_2d(m(outputs[i].cpu()).T.unsqueeze(0))[0]*3000
                            else:
                                # delt = dct.idct_2d(deltas[i, :, :length].T.unsqueeze(0))
                                outputs_raw = idct_2d(outputs[i, :, :length].cpu().T.unsqueeze(0))[0]*4000

                            for t in range(length):
                                fig_loc =opt.ckpt+"/Evaluation/"+opt.datetime
                                fig_loc += "/" + str(i) + "_" + str(label.item())
                                if label > 8:
                                    if not os.path.exists(fig_loc):
                                        os.makedirs(fig_loc)
                                    display_poses([org_raw[t].reshape([3,19])], save_loc=fig_loc, custom_name="outputs_", time=t, custom_title=None, legend_=None, color_list = ["red"])
                                    display_poses([org_raw[t].reshape([3,19]),outputs_raw[t].reshape([3,19])], save_loc=fig_loc, custom_name="inputs_", time=t, custom_title=None, legend_=None, color_list = ["red", "green"])
                        # display_poses([targ_raw[t].reshape([3,19])], save_loc=fig_loc, custom_name="targets_", time=t, custom_title=None, legend_=None, color_list = ["blue"])       
                    
                    ''' Fetching Method LOSS Computation '''
                    # whether_dtw_loss = input('Do you wanna compute DTW_loss?\n(y/n)')
                    whether_dtw_loss = 'n'
                    if whether_dtw_loss == 'y':                    
                        _, _, dtw_loss = test_corr_v4(test_loader, model, is_cuda=is_cuda)
                        pd.DataFrame(dtw_loss).to_csv('Results/Combined_v2/Evaluation/'+time+'dtw_loss_.csv')
                        with open('Data/DTW_Method.pickle', "rb") as f:
                            data = pickle.load(f)
                        targets_raw = data['targets']
                        targets_raw_reorder = targets[0:31]+targets[56:88]+targets[31:56]
                        dct_n = 25
                        targets = torch.from_numpy(np.array([dct_2d(torch.from_numpy(x))[:, :dct_n].numpy() if x.shape[1] >= dct_n else
                                            dct_2d(torch.nn.ZeroPad2d((0,dct_n - x.shape[1], 0, 0))(torch.from_numpy(x))).numpy()
                                            for x in targets_raw_reorder]).astype('double')).cuda().float()
                        _, pred_in = torch.max(model(inputs, labels, False)[2].data, 1) 
                        # deltas, _, _, = model(inputs, labels, False)
                        _, pred_out = torch.max(model(targets, labels, False)[2].data, 1)
                
                else:
                    deltas, _, y_pred = model(inputs)
                    _, pred_in = torch.max(y_pred.data, 1)  
                    
                    outputs = inputs+deltas
                    _, pred_out = torch.max(model(outputs)[2].data, 1)

    summary = np.vstack((labels.cpu().numpy(), pred_in.cpu().numpy(), pred_out.cpu().numpy())).T
    summary = pd.DataFrame(summary, columns=['label', 'original', 'corrected'])
    summary.to_csv(savepath+'EMT-'+ model_id+'.csv', mode='a', float_format='%6f')

    count = 0
    total = 0
    map_label = {0: ('SQUAT', 'Correct'), 1: ('SQUAT', 'Feets too wide'), 2: ('SQUAT', 'Knees inward'),
                 3: ('SQUAT', 'Not low enough'), 4: ('SQUAT', 'Front bended'), 5: ('SQUAT', 'Unknown'),
                 6: ('Lunges', 'Correct'), 7: ('Lunges', 'Not low enough'), 8: ('Lunges', 'Knees pass toes'),
                 9: ('Plank', 'Correct'), 10: ('Plank', 'Banana back'), 11: ('Plank', 'Rolled back')}
    corrects = {'SQUAT': 0, 'Lunges': 6, 'Plank': 9}
    results = {'SQUAT': {}, 'Lunges': {}, 'Plank': {}}
    for k, v in map_label.items():
        results[v[0]][v[1]] = {}
        tmp = summary[summary['label'] == k]

        if (len(tmp)==0) :
            # print('Detects 0 as a divisor, while k={} v={}'.format(k,v))
            results[v[0]][v[1]]['original']='nan'
            results[v[0]][v[1]]['corrected']='nan'
            continue

        results[v[0]][v[1]]['original'] = np.sum(tmp['label'] == tmp['original']) / len(tmp) * 100
        results[v[0]][v[1]]['corrected'] = np.sum(tmp['corrected'] == corrects[v[0]]) / len(tmp) * 100
        count = count + np.sum(tmp['corrected'] == corrects[v[0]])
        total = total + len(tmp)

    res = count / total * 100

    loss_matrix = pd.DataFrame(results)
    loss_matrix.to_csv(savepath+'EMT-'+ model_id+'.csv', mode='a', float_format='%6f')

# if __name__ == "__main__":
#     opt = Options().parse()

#     time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
#     savepath = opt.ckpt+'/Evaluation/'

#     if not os.path.exists(savepath):
#         os.makedirs(savepath)
#     savepath += opt.datetime
#     while os.path.exists(savepath):
#         savepath += "_x"

#     combined_model = GCN_corr_class_ours(hidden_feature=opt.hidden, p_dropout=opt.dropout, classes=12).cuda()
#     opt.model_dir = 'Results-22Spring/Combined_v2/models/2022-07-06-21-27.pt'

#     main_eval(time, savepath,  model_version='CCF22S', model_combined= combined_model, model_combined_path=opt.model_dir, options=opt)

#     print('Evaluation done')
    






 
