import pandas as pd
import numpy as np
import os
import argparse

import scipy.sparse as sp

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras import backend as K
from tensorflow.keras.regularizers import l2
from tensorflow.keras import metrics

from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn import preprocessing as pp

def splitData(X, binomial=False):
    if binomial:
        x = X.iloc[:, 3:]
        y = pd.DataFrame([X['mal_ratio'], 1-X['mal_ratio']],  index=['malignant', 'normal']).T
    else:  
        x = X.iloc[:, 2:]
        frac = X.iloc[:, :2]
        y = frac.divide(frac.sum(axis=1), axis=0)
    return x, y

def rmse(y_true, y_pred):
    return tf.sqrt(tf.reduce_mean(tf.math.squared_difference(y_true, y_pred)))

def tf_trans(X, scaler=None):
    # X (genes, samples)
    if scaler is None:
        return 1.0 * X / np.tile(np.sum(X,axis=0), (X.shape[0],1))
    else:
        return 1.0 * X /scaler.reshape(1, X.shape[1])

def tf_idf(X):
    #TF-IDF transformation
    idf = np.log(1.0 * X.shape[1] / np.sum(X,axis=1)+1)
    idf_diag = sp.diags(list(idf), offsets=0, shape=(X.shape[0], X.shape[0]), format="csr")
    X = idf_diag * tf_trans(X)
    
    return X, idf_diag

def preprocess(X, idf_diag=None, bulk_num = None):
    # X (samples, genes)
    if bulk_num is not None:
        X = X/bulk_num
    if idf_diag is None:
        X, idf_diag = tf_idf(X.T)
    else:
        X = idf_diag*tf_trans(X.T)
    X[np.isnan(X)] = 0
    if len(X) > 1:
        X = MinMaxScaler().fit_transform(X).T
    return X, idf_diag

class Net(object):
    def __init__(
        self,
        n_in,
        n_out,
        loss,
        model_name = 'dataset',
        hidden = [256, 128, 64, 32, 32, 32],
        dropout = [0, 0, 0, 0, 0, 0],
        num_category = 2, 
        epochs = 100, 
        activation = 'relu',
        optimizer = 'adam',
        large = False,
        early_stopping = False, 
        early_stopping_validation_fraction = 0.1, 
        early_stopping_patience = 40,
        validation_data_for_early_stopping = None,
        batch_size = 32,
        verbose = 0, 
        ):

        self.n_in = n_in
        self.n_out = n_out
        self.loss = loss
        self.name = model_name
        self.hidden = hidden
        self.drop = dropout
        self.act = activation
        self.epochs = epochs
        self.verbose = verbose
        self.early_stopping = early_stopping
        self.early_stopping_validation_fraction = early_stopping_validation_fraction
        self.early_stopping_patience = early_stopping_patience
        self.validation_data_for_early_stopping = validation_data_for_early_stopping
        self.optimizer = optimizer
        self.batch_size = batch_size

        self.model_fn(verbose=True, large=large)

    def model_fn(self, verbose=False, large=False):
        print('Build Model:', self.name)

        model = Sequential()
        model.add(Dense(self.hidden[0], input_dim=self.n_in, activation=self.act, kernel_regularizer=l2(0.001), name='Dense_1'))
        model.add(Dropout(self.drop[0]))
        model.add(Dense(self.hidden[1], activation=self.act, kernel_regularizer=l2(0.001), name='Dense_2'))
        model.add(Dropout(self.drop[1]))
        model.add(Dense(self.hidden[2], activation=self.act, kernel_regularizer=l2(0.001), name='Dense_3'))
        model.add(Dropout(self.drop[2]))
        if large:
            model.add(Dense(self.hidden[3], activation=self.act, kernel_regularizer=l2(0.001), name='Dense_4'))
            model.add(Dropout(self.drop[3]))
        
#             model.add(Dense(self.hidden[4], activation=self.act, kernel_regularizer=l2(0.001), name='Dense_5'))
#             model.add(Dropout(self.drop[4]))
#             model.add(Dense(self.hidden[5], activation=self.act, kernel_regularizer=l2(0.001), name='Dense_6'))
#             model.add(Dropout(self.drop[5]))
        if self.n_out == 1:
            model.add(Dense(self.n_out, activation='sigmoid', name='output'))
        else:
            model.add(Dense(self.n_out, activation='softmax', name='output'))

        if verbose:
            model.summary()

        self.model = model

    def fit(self, X, y, X_val=None, y_val=None, epochs = None, verbose = None):
        self.model.compile(loss=self.loss, optimizer = self.optimizer, metrics=[rmse, 'mse', metrics.mae])

        if epochs is not None:
            self.epochs = epochs
        if verbose is None:
            verbose = self.verbose
        if X_val is None:
            X_tr, X_val, y_tr, y_val = train_test_split(X, 
                                                        y,
                                                        test_size = self.early_stopping_validation_fraction,
                                                        shuffle=True)
        else:
            X_tr, y_tr = X, y
            
        validation_data = (X_val, y_val)

        if self.early_stopping:
            callbacks = [EarlyStopping(monitor = 'val_loss', patience = self.early_stopping_patience, verbose = 1)]
        else:
            callbacks = None
        
        history = self.model.fit(X_tr, y_tr, batch_size = self.batch_size,
         epochs = self.epochs, validation_data = validation_data, callbacks = callbacks, shuffle = True, verbose = verbose)

        return history
    
def main(data):

    keep_info = {
        'train_ind':[],
        'test_ind':[],
        'keep_genes':[],
        'model':[],
        'idf_tr':[],
        'idf_val':[]
    }

    architectures = {'m256':    ([256, 128, 64, 32],    [0, 0, 0, 0]),
                    'm512':    ([512, 256, 128, 64],   [0, 0.3, 0.2, 0.1]),
                    'm1024':   ([64, 32, 16, 16, 8], [0, 0, 0, 0, 0, 0])}
    test_genes = pd.read_csv('./aml_subject_data/common_gene.txt', index_col=0)
    keep_gene = ['malignant', 'normal']+list(test_genes['gene'].values)
    # for ind in range(15):
    # name = subjects[ind]

    # rec = pd.read_csv('./gene_expression_recurrent.txt', sep='\t', index_col=0) 
    # pri = pd.read_csv('./gene_expression_primary.txt', sep='\t', index_col=0) 

    # pri_fpkm = pd.read_csv('./gdc_bulk_primary.txt', index_col=0)
    # rec_fpkm = pd.read_csv('./gdc_bulk_recurrent.txt', index_col=0)

    # select = pd.concat([rec.sample(frac=0.7), pri.sample(frac=0.7)], axis=0)
    # select_fpkm = pd.concat([rec_fpkm.sample(frac=0.5), pri_fpkm.sample(frac=0.5)], axis=0)
    # train_ind = [0, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14]
    for i in range(15):
        train_ind = list(range(i))  + list(range(i+1, 15))
        print(train_ind)
        train = pd.concat([data[i][keep_gene] for i in train_ind], axis=0, ignore_index=True)
        # val = pri_fpkm[keep_gene]
        val = data[i][keep_gene]
        
        X_tr, y_tr = splitData(train)
        X_val, y_val = splitData(val)

        X_tr1, x_tr1_idf = preprocess(X_tr)
        # select_x, select_idf = preprocess(select_fpkm.loc[:, list(test_genes['gene'].values)].values)
        # select_y =  select_fpkm.loc[:, ['malignant', 'normal']]

        # X_tr, y_tr = np.concatenate([X_tr1, select_x], axis=0) \
        #             , pd.concat([y_tr, select_y], axis=0, ignore_index=True)
        

        celltypes = y_tr.columns
        nor_X_tr = X_tr1
        nor_y_tr = y_tr.values
        nor_X_val_scale, idf_val = preprocess(X_val.values)
        nor_y_val_scale = y_val.loc[:, celltypes].values
        
        epochs = 500
        opt = tf.keras.optimizers.Adam(learning_rate=0.0001, beta_1=0.9, beta_2=0.999)
        m256 = Net(nor_X_tr.shape[1], 2, loss=rmse, model_name='m1024', optimizer=opt, large=True,
                    early_stopping=True, hidden=architectures['m256'][0], dropout=architectures['m256'][1])
        h_256 = m256.fit(nor_X_tr, nor_y_tr, X_val=nor_X_val_scale, y_val=nor_y_val_scale, epochs=epochs)
        keep_info['model'].append(m256)
        keep_info['idf_tr'].append(x_tr1_idf)
        keep_info['idf_val'].append(idf_val)

        idf_path = path + 'idfs/'
        model_path = path + 'models/'
        pred_path = path + 'prediction/'
        if not os.path.exists(idf_path):
            os.makedirs(idf_path)

        if not os.path.exists(model_path):
            os.makedirs(model_path) 

        if not os.path.exists(pred_path):
            os.makedirs(pred_path)
        
        # name = 'whole'
        name = subjects[i]
        sp.save_npz(idf_path+name+'_normalized_m256_test.npz', idf_val)
        # sp.save_npz(idf_path+name+'_normalized_m256_train.npz', x_tr1_idf)
        # sp.save_npz(idf_path+name+'_normalized_m256_select.npz', select_idf)
        m256.model.save(model_path+name+'_deepdecon_tf_idf_normalized_m256.h5')
        
        nor_X_val_scale, idf_val = preprocess(X_val.values)
        pred = m256.model.predict(nor_X_val_scale)
        pd.DataFrame(pred, columns=['malignant', 'normal']).to_csv(pred_path+name+'_deepdecon_tf_idf_m256_predictions.txt')

        # nor_X_val_scale, _ = preprocess(X_val.values, x_tr1_idf)
        # pred = m256.model.predict(nor_X_val_scale)
        # pd.DataFrame(pred, columns=['malignant', 'normal']).to_csv(pred_path+name+'_deepdecon_tf_idf_m256_predictions_train.txt')

        # nor_X_val_scale, _ = preprocess(X_val.values, select_idf)
        # pred = m256.model.predict(nor_X_val_scale)
        # pd.DataFrame(pred, columns=['malignant', 'normal']).to_csv(pred_path+name+'_deepdecon_tf_idf_m256_predictions_select.txt')

        print(idf_path+name+'_normalized_m256.npz saved')

 
if __name__ == "__main__":
    # main()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells", type=int, help="Number of cells to use for each bulk sample.", default=500)
    parser.add_argument("--path", type=str, help="training data directory", default='./aml_simulated_bulk_data/range_0_10/')
    parser.add_argument("--start", type=int, help="fraction start range of generated samples e.g. 0 for [0, 100]", default=0)
    parser.add_argument("--end", type=int, help="fraction end range of generated samples e.g. 0 for [0, 100]", default=100)
    args = parser.parse_args()

    cell = args.cells
    path = args.path
    start = args.start
    end = args.end

    subjects = ['AML328-D29', 'AML1012-D0', 'AML556-D0', 'AML328-D171', 
                'AML210A-D0', 'AML419A-D0', 'AML328-D0', 'AML707B-D0',
                'AML916-D0', 'AML328-D113', 'AML329-D0', 'AML420B-D0',
                'AML329-D20', 'AML921A-D0', 'AML475-D0'
            ]
    
    for subject in subjects:
        path = "./aml_simulated_bulk_data/sample_" + str(cell) + "/range_" + str(start) + "_" + str(end) + "/"
        data = []
        for sub in subjects:
            tmp = pd.read_csv(path+sub+'_bulk_nor_'+ str(cell) +'_200.txt', index_col=0)
            data.append(tmp)
        main(data)