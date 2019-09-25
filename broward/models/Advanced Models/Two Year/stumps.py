import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold, GridSearchCV
from sklearn.metrics import roc_auc_score
from utils.fairness_functions import compute_fairness



def stump_cv(X, Y, columns, c_grid, seed):
    
    ## estimator
    lasso = LogisticRegression(class_weight = 'balanced', solver='liblinear', random_state=seed, penalty='l1')
    
    ## outer cv
    train_outer = []
    test_outer = []
    outer_cv = KFold(n_splits=5, random_state=seed, shuffle=True)

    ## 5 sets of train & test index
    for train, test in outer_cv.split(X, Y):
        train_outer.append(train)
        test_outer.append(test)   
    
    ## storing lists
    holdout_auc = []
    best_params = []
    auc_diffs = []
    fairness_overviews = []
    confusion_matrix_rets = []
    
    ## inner cv
    inner_cv = KFold(n_splits=5, shuffle=True, random_state=seed)
    
    for i in range(len(train_outer)):

        ## subset train & test sets in inner loop
        train_x, test_x = X.iloc[train_outer[i]], X.iloc[test_outer[i]]
        train_y, test_y = Y[train_outer[i]], Y[test_outer[i]]
        
        ## holdout test with "race" for fairness
        holdout_with_attrs = test_x.copy()
        
        ## remove unused feature in modeling
        train_x = train_x.drop(['person_id', 'screening_date', 'race'], axis=1)
        test_x = test_x.drop(['person_id', 'screening_date', 'race'], axis=1)
        
        ## GridSearch: inner CV
        clf = GridSearchCV(estimator=lasso, param_grid=c_grid, scoring='roc_auc',
                           cv=inner_cv, return_train_score=True).fit(train_x, train_y)
    
        ## best parameter & scores
        mean_train_score = clf.cv_results_['mean_train_score']
        mean_test_score = clf.cv_results_['mean_test_score']        
        best_param = clf.best_params_
        auc_diffs.append(mean_train_score[np.where(mean_test_score == clf.best_score_)[0][0]] - clf.best_score_)
        
        ## run model with best parameter
        best_model = LogisticRegression(class_weight = 'balanced', solver='liblinear', 
                                        random_state=seed, penalty='l1', C=best_param['C']).fit(train_x, train_y)
        coefs = best_model.coef_[best_model.coef_ != 0]
        features = columns[best_model.coef_[0] != 0].tolist()
        intercept = round(best_model.intercept_[0],3)
        
        ## dictionary
        lasso_dict_rounding = {}
        for i in range(len(features)):
            lasso_dict_rounding.update({features[i]: round(coefs[i], 3)})
        
        ## prediction on test set
        prob = 0
        for k in features:
            test_values = test_x[k]*(lasso_dict_rounding[k])
            prob += test_values
        holdout_prob = np.exp(prob)/(1+np.exp(prob))
        holdout_pred = (holdout_prob > 0.5)
        
    
        ## fairness 
        holdout_fairness_overview = compute_fairness(df=holdout_with_attrs,
                                                     preds=holdout_pred,
                                                     labels=test_y)
        fairness_overviews.append(holdout_fairness_overview)
        ## confusion matrix stats
        confusion_matrix_fairness = compute_confusion_matrix_stats(df=holdout_with_attrs,
                                                     preds=holdout_pred,
                                                     labels=test_y, protected_variables=["sex", "race"])
        cf_final = confusion_matrix_fairness.assign(fold_num = [i]*confusion_matrix_fairness['Attribute'].count())
        confusion_matrix_rets.append(cf_final)
    
        ## store results
        holdout_auc.append(roc_auc_score(test_y, holdout_prob))
        best_params.append(best_param)
        
    df = pd.concat(confusion_matrix_rets, ignore_index=True)
    df.sort_values(["Attribute", "Attribute Value"], inplace=True)
    return {'best_params': best_params,
            'holdout_test_auc': holdout_auc,
            'auc_diffs': auc_diffs,
            'fairness_overview': fairness_overviews,
            'confusion_matrix_stats': df
           }





def stump_model(X_train, Y_train, X_test, Y_test, c, columns, seed):
        
    ## remove unused feature in modeling
    X_train = X_train.drop(['person_id', 'screening_date', 'race'], axis=1)
    X_test = X_test.drop(['person_id', 'screening_date', 'race'], axis=1)
    
    ## estimator
    lasso = LogisticRegression(class_weight = 'balanced', solver='liblinear', 
                               random_state=seed, penalty='l1', C = c).fit(X_train, Y_train)
    coefs = lasso.coef_[lasso.coef_ != 0]
    features = columns[lasso.coef_[0] != 0].tolist()
    intercept = round(lasso.intercept_[0],3)
     
    ## dictionary
    lasso_dict_rounding = {}
    for i in range(len(features)):
        lasso_dict_rounding.update({features[i]: round(round(coefs[i], 3)*100, 1)})
    
    ## prediction on test set
    prob = 0
    for k in features:
        test_values = X_test[k]*(lasso_dict_rounding[k]/100)
        prob += test_values
    
    holdout_prob = np.exp(prob)/(1+np.exp(prob))
    test_auc = roc_auc_score(Y_test, holdout_prob)
    
    return {'coefs': coefs, 
            'features': features, 
            'intercept': intercept, 
            'dictionary': lasso_dict_rounding, 
            'test_auc': test_auc}
    
    
def stump_table(coefs, features, intercept, dictionary):
    
    print('+-----------------------------------+----------------+')
    print('|', 'Features', '{n:>{ind}}'.format(n = '|', ind=26), 'Score', '{n:>{ind}}'.format(n = '|', ind=10))
    print('|====================================================|')
    for i in range(len(dictionary)):
        print('|', features[i], '{n:>{ind}}'.format(n = '|', ind=35 - len('|'+features[i])),dictionary[features[i]], '{n:>{ind}}'.format(n = '|', ind = 15 - len(np.str(dictionary[features[i]]))))
    print('|', 'Intercept', '{n:>{ind}}'.format(n = '|', ind=25), round(intercept, 3), '{n:>{ind}}'.format(n = '|', ind = 15 - len(np.str(intercept)))) 
    print('|====================================================|')
    print('|', 'ADD POINTS FROM ROWS 1 TO', len(dictionary), '{n:>{ind}}'.format(n = '|', ind = 6), 'Total Score', '{n:>{ind}}'.format(n = '|', ind = 4))
    print('+-----------------------------------+----------------+')    
    
    
def latex_stump_table(coefs, features, intercept, dictionary):
    print('\\begin{tabular}{|l|r|r|} \\hline')
    for i in range(len(dictionary)):
        sign = '+' if dictionary[features[i]] >= 0 else '-'
        print('{index}.'.format(index = i+1), features[i].replace('_', '\_'), '&',np.abs(dictionary[features[i]]), '&', sign+'...', '\\\\ \\hline')
    print('{}.'.format(len(dictionary)+1), 'Intercept', '&', round(intercept, 3), '&', sign+'...', '\\\\ \\hline')
    print('\\textbf{{ADD POINTS FROM ROWS 1 TO {length}}}  &  \\textbf{{SCORE}} & = ..... \\\\ \\hline'.format(length=len(dictionary)+1))
    print('\\multicolumn{3}{l}{Pr(Y = 1) = exp(score/100) / (1 + exp(score/100))} \\\\ \\hline')
    
          
def stump_plots(features, coefs):
    
    import numpy as np
    import matplotlib.pyplot as plt
    
    def stump_visulization(label, sub_features, features, coefs):
        cutoffs = []
        cutoff_values = []        
        cutoff_prep = []
        cutoff_values_prep = []
        
        ## select features
        if label == 'age_at_current_charge':
            
            ## sanity check
            if len(sub_features) == 1:
                cutoffs.append(int(sub_features[0][sub_features[0].find('=')+1:]))
                cutoff_values.append(coefs[np.where(np.array(features) == sub_features[0])[0][0]])
                
                ## prepare values
                cutoff_prep.append(np.linspace(18, cutoffs[0]+0.5, 1000))
                cutoff_prep.append(np.linspace(cutoffs[0]+0.5, 70, 1000))
                cutoff_values_prep.append(np.repeat(cutoff_values[0], 1000))
                cutoff_values_prep.append(np.repeat(0, 1000))
                
                plt.figure(figsize=(4,3))
                plt.scatter(cutoff_prep, cutoff_values_prep, s=0.05)
                #plt.vlines(x=cutoffs[0]+0.5, ymin=0, ymax=cutoff_values[0], colors='C0', linestyles='dashed')
                plt.title(label)
                plt.ylabel('probability')
                plt.show()
            else:
                for j in sub_features:
                    cutoff_values.append(coefs[np.where(np.array(features) == j)[0][0]])
                    cutoffs.append(int(j[j.find('=')+1:])) 
                
                cutoffs.insert(0,18)
                cutoffs.append(70)
                cutoff_values.append(0)
                
                ## prepare cutoff values for plots
                for n in range(len(cutoffs)-1):
                    cutoff_prep.append(np.linspace(cutoffs[n]+0.5, cutoffs[n+1]+0.5, 1000))
                    cutoff_values_prep.append(np.repeat(np.sum(cutoff_values[n:]), 1000)) 
                    
                ## visulization
                unique = np.unique(cutoff_values_prep)[::-1]
                unique_len = len(unique)
                plt.figure(figsize=(4,3))
                plt.scatter(cutoff_prep, cutoff_values_prep, s=0.05)
                #for m in range(1,unique_len):
                #    plt.vlines(x=cutoffs[m]-0.5, ymin=unique[m], ymax=unique[m-1], colors = "C0", linestyles='dashed')
                plt.title(label)
                plt.ylabel('probability')
                plt.show()
        else:
            ## sanity check
            if len(sub_features) == 1:
                cutoffs.append(int(sub_features[0][sub_features[0].find('=')+1:]))
                cutoff_values.append(coefs[np.where(np.array(features) == sub_features[0])[0][0]])
                
                ## prepare values
                cutoff_prep.append(np.linspace(-0.5, cutoffs[0]-0.5, 1000))
                cutoff_prep.append(np.linspace(cutoffs[0]-0.5, cutoffs[0]+0.5, 1000))
                cutoff_values_prep.append(np.repeat(0, 1000))
                cutoff_values_prep.append(np.repeat(cutoff_values[0], 1000))
                
                plt.figure(figsize=(4,3))
                plt.scatter(cutoff_prep, cutoff_values_prep, s=0.05)
                #plt.vlines(x=cutoffs[0]-0.5, ymin=0, ymax=cutoff_values[0], colors='C0', linestyles='dashed')
                plt.title(label)
                plt.ylabel('probability')
                plt.show()     
            else:
                for j in sub_features:
                    cutoff_values.append(coefs[np.where(np.array(features) == j)[0][0]])
                    cutoffs.append(int(j[j.find('=')+1:])) 
                
                ## prepare cutoff values for plots
                cutoff_prep = []
                cutoff_values_prep = []
                
                for n in range(len(cutoffs)-1):
                    cutoff_prep.append(np.linspace(cutoffs[n]-0.5, cutoffs[n+1]-0.5, 1000))
                    cutoff_values_prep.append(np.repeat(np.sum(cutoff_values[:n+1]), 1000))    
                cutoff_prep.append(np.linspace(cutoffs[-1]-0.5, cutoffs[-1]+0.5, 1000))
                cutoff_values_prep.append(np.repeat(np.sum(cutoff_values), 1000))   
                
                ## visualization
                unique = np.unique(cutoff_values_prep)
                unique_len = len(unique)
                plt.figure(figsize=(4,3))
                plt.scatter(cutoff_prep, cutoff_values_prep, s=0.05)
                #for m in range(1, unique_len):
                #    plt.vlines(x=cutoffs[m]-0.5, ymin=unique[m], ymax=unique[m-1], colors = "C0", linestyles='dashed')
                plt.title(label)
                plt.ylabel('probability')
                plt.show()  
                
    
    labels = ['Gender', 'age_at_current_charge', 'arrest', 'charges', 'violence', 'felony', 'misdemeanor', 'property', 'murder', 
          'assault', 'sex_offense', 'weapon', 'felprop_viol', 'felassault', 'misdeassult', 'traffic', 'drug', 'dui', 
          'stalking', 'voyeurism', 'fraud', 'stealing', 'trespass', 'ADE', 'Treatment', 'prison', 'jail', 'fta_two_year', 
          'fta_two_year_plus', 'pending_charge', 'probation', 'SentMonths', 'six_month', 'one_year', 'three_year', 
          'five_year', 'current_violence']
    
    for i in labels:
        sub_features = np.array(np.array(features)[[i in k for k in features]])
        if len(sub_features) == 0:
            continue
        stump_visulization(i, sub_features, features, coefs)
    
 
    