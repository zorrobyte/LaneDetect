import torch
import numpy as np 
import os
from collections import defaultdict
import torch.nn as nn
import cv2

'''
二向语义分割函数
'''
###计算class weights
def bi_weight(data,batch):
    frequency=defaultdict(lambda:torch.tensor(0.))
    for i in range(batch):                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      
        img_tensor=data[i,:,:]
        frequency['background']+=(img_tensor==0.).sum()
        frequency['lane']+=(img_tensor==1.).sum()
    class_weights=defaultdict(lambda:torch.tensor(0.))
    class_weights['background']=1./torch.log(1.02+frequency['background']/(frequency['background']+frequency['lane']))
    class_weights['lane']=1./torch.log(1.02+frequency['lane']/(frequency['background']+frequency['lane']))
    return class_weights

###CrossEntropy损失函数
def Segmentation_loss(predictions,label,class_weights):
    loss=nn.CrossEntropyLoss(weight=torch.tensor([class_weights['background'].item(),class_weights['lane'].item()]).cuda())
    label=label.type(torch.long)
    loss=loss(predictions,label)
    return loss	

'''
聚类损失函数
'''
def variance(delta_v,embeddings,labels):
    num_samples=labels.size(0)
    var_loss=torch.tensor(0.).cuda()
    for i in range(num_samples):
        sample_embedding=embeddings[i,:,:,:]
        sample_label=labels[i,:,:]
        num_clusters=len(sample_label.unique())-1
        vals=sample_label.unique()
        sample_label=sample_label.view(sample_label.size(0)*sample_label.size(1))
        sample_embedding=sample_embedding.view(-1,sample_embedding.size(1)*sample_embedding.size(2))
        loss=torch.tensor(0.).cuda()
        for j in range(num_clusters):
            indices=(sample_label==vals[j]).nonzero()
            indices=indices.squeeze()
            cluster_elements=torch.index_select(sample_embedding,1,indices)
            Nc=cluster_elements.size(1)
            mean_cluster=cluster_elements.mean(dim=1,keepdim=True)
            distance=torch.norm(cluster_elements-mean_cluster)
            loss+=torch.pow((torch.clamp(distance-delta_v,min=0.)),2).sum()/Nc
        var_loss+=loss/num_clusters
    return var_loss/num_samples

def distance(delta_d,embeddings,labels):
    num_samples=labels.size(0)
    dis_loss=torch.tensor(0.).cuda()
    for i in range(num_samples):
        clusters=[]
        sample_embedding=embeddings[i,:,:,:]
        sample_label=labels[i,:,:]
        num_clusters=len(sample_label.unique())-1
        vals=sample_label.unique()
        sample_label=sample_label.view(sample_label.size(0)*sample_label.size(1))
        sample_embedding=sample_embedding.view(-1,sample_embedding.size(1)*sample_embedding.size(2))
        loss=torch.tensor(0.).cuda()
        for j in range(num_clusters):
            indices=(sample_label==vals[j]).nonzero()
            indices=indices.squeeze()
            cluster_elements=torch.index_select(sample_embedding,1,indices)
            mean_cluster=cluster_elements.mean(dim=1)
            clusters.append(mean_cluster)
        for index in range(num_clusters):
            for idx,cluster in enumerate(clusters):
                if index==idx:
                    continue
                else:
                    distance=torch.norm(clusters[index]-cluster)
                    loss+=torch.pow(torch.clamp(delta_d-distance,min=0.),2)
        dis_loss+=loss/(num_clusters*(num_clusters-1))
    return dis_loss/num_samples

def reg(embeddings,labels):
    num_samples=labels.size(0)
    reg_loss=torch.tensor(0.).cuda()
    for i in range(num_samples):
        sample_embedding=embeddings[i,:,:,:]
        sample_label=labels[i,:,:]
        num_clusters=len(sample_label.unique())-1
        vals=sample_label.unique()
        sample_label=sample_label.view(sample_label.size(0)*sample_label.size(1))
        sample_embedding=sample_embedding.view(-1,sample_embedding.size(1)*sample_embedding.size(2))
        loss=torch.tensor(0.).cuda()
        for j in range(num_clusters):
            indices=(sample_label==vals[j]).nonzero()
            indices=indices.squeeze()
            cluster_elements=torch.index_select(sample_embedding,1,indices)
            mean_cluster=cluster_elements.mean(dim=1)
            euclidean=torch.sum(torch.abs(mean_cluster))
            if torch.isnan(euclidean):
                print(cluster_elements)
                print('labels:{},c:{}'.format(sample_label.unique(),num_clusters))
            loss+=euclidean
        reg_loss+=loss/num_clusters
    return reg_loss/num_samples

def instance_loss(delta_v,delta_d,embeddings,labels):
    variance_loss=variance(delta_v,embeddings,labels)
    distance_loss=distance(delta_d,embeddings,labels)
    reg_loss=reg(embeddings,labels)
    total_loss=variance_loss+distance_loss+.001*reg_loss
    return total_loss,variance_loss,distance_loss,reg_loss

class Losses:

    '''
    Implement above losses in a object oriented fashion
    '''
    # data,batch,predictions,label,class_weights,delta_v,embeddings,labels,delta_d,embeddings,labels,embeddings,labels
    def __init__(self,data,batch,predictions,seg_mask,
                 embeddings,instance_mask,delta_v=.5,delta_d=3,
                 alpha=1,beta=1,gamma=0):
        '''
        Attributes:
            data:输入数据
            batch:每个训练循环的数据数
            predictions:LaneNet语义分割输出
            seg_mask:语义分割Ground-truth
            embeddings:Lanenet高阶投影结果
            instance_mask:个体分割Ground-truth
            delta_v:Variance损失的hinge节点
            delta_d:Distance损失的hinge节点
            alpha:Variance损失的权重
            beta:Distance损失的权重
            gamma:Regularization损失的权重
        '''
        self.data=data
        self.batch=batch
        self.predictions=predictions
        self.seg_mask=seg_mask
        self.embeddings=embeddings
        self.instance_mask=instance_mask
        self.delta_v=delta_v
        self.delta_d=delta_d
        self.alpha=alpha
        self.beta=beta 
        self.gamma=gamma

    def _bi_weight(self):
        frequency=defaultdict(lambda:torch.tensor(0.))
        for i in range(self.batch):                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      
            img_tensor=self.data[i,:,:]
            frequency['background']+=(img_tensor==0.).sum()
            frequency['lane']+=(img_tensor==1.).sum()
        class_weights=defaultdict(lambda:torch.tensor(0.))
        class_weights['background']=1./torch.log(1.02+frequency['background']/(frequency['background']+frequency['lane']))
        class_weights['lane']=1./torch.log(1.02+frequency['lane']/(frequency['background']+frequency['lane']))
        return class_weights

    def _segmentation_loss(self):
        class_weights=self._bi_weight()
        loss=nn.CrossEntropyLoss(weight=torch.tensor([class_weights['background'].item(),class_weights['lane'].item()]).cuda())
        label=self.seg_mask.type(torch.long)
        loss=loss(self.predictions,label)
        return loss

    def _discriminative_loss(self):
        num_samples=self.instance_mask.size(0)
        dis_loss=torch.tensor(0.).cuda()
        var_loss=torch.tensor(0.).cuda()
        reg_loss=torch.tensor(0.).cuda()
        for i in range(num_samples):
            clusters=[]
            sample_embedding=self.embeddings[i,:,:,:]
            sample_label=self.instance_mask[i,:,:]
            num_clusters=len(sample_label.unique())-1
            vals=sample_label.unique()
            sample_label=sample_label.view(sample_label.size(0)*sample_label.size(1))
            sample_embedding=sample_embedding.view(-1,sample_embedding.size(1)*sample_embedding.size(2))
            v_loss=torch.tensor(0.).cuda()
            d_loss=torch.tensor(0.).cuda()
            r_loss=torch.tensor(0.).cuda()
            for j in range(num_clusters):
                indices=(sample_label==vals[j]).nonzero()
                indices=indices.squeeze()
                cluster_elements=torch.index_select(sample_embedding,1,indices)
                Nc=cluster_elements.size(1)
                mean_cluster=cluster_elements.mean(dim=1,keepdim=True)
                clusters.append(mean_cluster)
                v_loss+=torch.pow((torch.clamp(torch.norm(cluster_elements-mean_cluster)-self.delta_v,min=0.)),2).sum()/Nc
                r_loss+=torch.sum(torch.abs(mean_cluster))
            for index in range(num_clusters):
                for idx,cluster in enumerate(clusters):
                    if index==idx:
                        continue
                    else:
                        d_loss+=torch.pow(torch.clamp(self.delta_d-torch.norm(clusters[index]-cluster),min=0.),2)
            var_loss+=v_loss/num_clusters
            dis_loss+=d_loss/(num_clusters*(num_clusters-1))
            reg_loss+=r_loss/num_clusters
        return self.alpha*(var_loss/num_samples)+self.beta*(dis_loss/num_samples)+self.gamma*(reg_loss/num_samples)

    def _total_loss(self):
        return self._segmentation_loss()+self._discriminative_loss()

    def __call__(self):
        return self._total_loss()





