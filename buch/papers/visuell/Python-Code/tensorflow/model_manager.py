import os
import numpy as np
import tensorflow as tf
import time


import dataset_plotter as plotter
from model import Model
from dataset_info import DatasetInfo

from prog_train import ProgressTrain

from gabor_layer import GaborLayer
from util import ProgressBar

class ModelManager:
    def __init__(self):
        print('TF version ', tf.__version__)
        self.built = False
    
    def normalize(self, x):
        x = x.astype('float32')
        minX = np.min(x)
        maxX = np.max(x)
        x = (x-minX) / (maxX-minX)
        return x
            
            
    def printNumberOfWeights(self):
        print('---------- Form of the model and number of weights: ----------')
        total_parameters = 0
        for variable in tf.trainable_variables():
            # shape is an array of tf.Dimension
            shape = variable.get_shape()
            print(variable.name + ' shape: ', end='')
            print(shape)
            variable_parameters = 1
            for dim in shape:
                variable_parameters *= dim.value
            total_parameters += variable_parameters
        print('Total parameters: ' + str(total_parameters))
    
#    def factorization(self, n):
#        for i in range(int(sqrt(float(n))), 0, -1):
#          if n % i == 0:
#            if i == 1: print('Who would enter a prime number of filters')
#            return (i, int(n / i))
#        
#    def put_kernels_on_grid (self, kernel, pad = 1):
#
#      '''Visualize conv. filters as an image (mostly for the 1st layer).
#      Arranges filters into a grid, with some paddings between adjacent filters.
#      Args:
#        kernel:            tensor of shape [Y, X, NumChannels, NumKernels]
#        pad:               number of black pixels around each filter (between them)
#      Return:
#        Tensor of shape [1, (Y+2*pad)*grid_Y, (X+2*pad)*grid_X, NumChannels].
#      '''
#      # get shape of the grid. NumKernels == grid_Y * grid_X
#      (grid_Y, grid_X) = self.factorization (kernel.get_shape()[3].value)
#    
#      x_min = tf.reduce_min(kernel)
#      x_max = tf.reduce_max(kernel)
#      kernel = (kernel - x_min) / (x_max - x_min)
#    
#      # pad X and Y
#      x = tf.pad(kernel, tf.constant( [[pad,pad],[pad, pad],[0,0],[0,0]] ), mode = 'CONSTANT')
#    
#      # X and Y dimensions, w.r.t. padding
#      Y = kernel.get_shape()[0] + 2 * pad
#      X = kernel.get_shape()[1] + 2 * pad
#    
#      channels = kernel.get_shape()[2]
#    
#      # put NumKernels to the 1st dimension
#      x = tf.transpose(x, (3, 0, 1, 2))
#      # organize grid on Y axis
#      x = tf.reshape(x, tf.stack([grid_X, Y * grid_Y, X, channels]))
#    
#      # switch X and Y axes
#      x = tf.transpose(x, (0, 2, 1, 3))
#      # organize grid on X axis
#      x = tf.reshape(x, tf.stack([1, X * grid_X, Y * grid_Y, channels]))
#    
#      # back to normal order (not combining with the next step for clarity)
#      x = tf.transpose(x, (2, 1, 3, 0))
#    
#      # to tf.image_summary order [batch_size, height, width, channels],
#      #   where in this case batch_size == 1
#      x = tf.transpose(x, (3, 0, 1, 2))
#    
#      # scaling to [0, 255] is not necessary for tensorboard
#    return x
    
    def createLogDir(self, outputDir):
        # Create Output Directories
        print('Create output directories..')
        timeStr = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        
        self.writerDir = outputDir + '/' + timeStr
        
        os.makedirs(self.writerDir)
        return self.writerDir
    
    def getData(self, maxDataSize, gaborInput, features1, filterSize1):
        self.filterSize1 = filterSize1
        self.gaborInput = gaborInput
        self.features1 = features1
        print("Getting data")
        (xTrain, yTrain), (xTest, yTest) = tf.keras.datasets.cifar10.load_data()
        xTrain = tf.image.rgb_to_grayscale(xTrain) # Convert to grayscale
        xTest = tf.image.rgb_to_grayscale(xTest)
        self.filterBank = None
        if self.gaborInput:
            gl = GaborLayer()
            self.filterBank, _ = gl.genFilterBank(self.features1, size=self.filterSize1)
                
        print('Calculating labels as one-hot')
        with tf.Session() as sess:
            oneHotTrain =  tf.one_hot(yTrain, 10)
            oneHotTest = tf.one_hot(yTest, 10)
            yTrain = sess.run(oneHotTrain)
            yTest = sess.run(oneHotTest)
        
        print('Creating datasets')
        self.trainBatch = tf.data.Dataset.from_tensor_slices({'x': xTrain, 'y': yTrain})
        self.testBatch = tf.data.Dataset.from_tensor_slices({'x': xTest, 'y': yTest})
        self.datasetInfo = DatasetInfo(self.trainBatch)
        self.datasetInfo.printInfo()
        self.maxDataSize = maxDataSize

        self.testBatch = self.testBatch.shuffle(self.maxDataSize)
        self.trainBatch = self.trainBatch.shuffle(self.maxDataSize)

    
    def build(self, miniBatchSize):
        self.built = True
        self.mdl = Model(self.datasetInfo)
        
        print('Define MiniBatch iteration') 
        with tf.name_scope('miniBatchIteration'):
            
            trainMiniBatches = self.trainBatch.batch(miniBatchSize, drop_remainder=False)
            testMiniBatches = self.testBatch.batch(miniBatchSize, drop_remainder=False)
            
            # Prefetch data to improove performance
            trainMiniBatches = trainMiniBatches.prefetch(1)
            
            #trainMiniBatches and testMiniBatches have the same item shape
            self.iterator = tf.data.Iterator.from_structure(trainMiniBatches.output_types,
                                                       trainMiniBatches.output_shapes)
            nextMiniBatch = self.iterator.get_next()
            
            self.training_init_op = self.iterator.make_initializer(trainMiniBatches)
            self.testing_init_op = self.iterator.make_initializer(testMiniBatches)
            
            self.x = tf.cast(nextMiniBatch['x'], tf.float32)
            self.x.set_shape(self.datasetInfo.inputshape)
            self.y = tf.cast(nextMiniBatch['y'], tf.float32)
            self.y.set_shape([None, self.datasetInfo.transitionCount, self.datasetInfo.classCount])
        
        print('Build model')
        with tf.name_scope('model'):
            self.mdl.build(self.x, self.y, self.gaborInput, self.features1, self.filterBank, self.filterSize1)
        
    def train(self, outputDir, numEpochs):
        assert (self.datasetInfo != None), "Call getData first"
        assert (os.path.exists(outputDir)), "Create Output Directories first"
        
        # enable GPU
        #config = tf.ConfigProto( device_count = {'GPU': 1 , 'CPU': 56} )
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        # start session
        self.sess = tf.Session(config=config)
        
        # prepare log writers
        print('prepare train writer')
        trainWriter = tf.summary.FileWriter(self.writerDir, self.sess.graph)
        print('prepare test writer')
        testWriter = tf.summary.FileWriter(self.writerDir + '/test')
        print('create summaries')
        tf.summary.scalar('Loss', self.mdl.loss)
        tf.summary.scalar('Accuracy', self.mdl.accuracy)
        if not self.gaborInput:
            tf.summary.histogram("weights1", self.mdl.kernel1)
            tf.summary.histogram("biases1", self.mdl.biases1)
       
        # scale weights to [0 255] and convert to uint8 (maybe change scaling?)
        x_min = tf.reduce_min(self.mdl.kernel1)
        x_max = tf.reduce_max(self.mdl.kernel1)
        weights_0_to_1 = (self.mdl.kernel1 - x_min) / (x_max - x_min)
        weights_0_to_255_uint8 = tf.image.convert_image_dtype (weights_0_to_1, dtype=tf.uint8)
    
        # to tf.image_summary format [batch_size, height, width, channels]
        weights_transposed = tf.transpose (weights_0_to_255_uint8, [3, 0, 1, 2])

        tf.summary.image("kernel_layer_1", weights_transposed, max_outputs=self.features1)
        tf.summary.histogram("weights2", self.mdl.kernel2)
        tf.summary.histogram("biases2", self.mdl.biases2)
        tf.summary.histogram("weights3", self.mdl.kernel3)
        tf.summary.histogram("biases3", self.mdl.biases3)
        tf.summary.histogram("fcWeights1", self.mdl.fc1Weights)
        tf.summary.histogram("fcBiases1", self.mdl.fc2Biases)
        tf.summary.histogram("fcWeights2", self.mdl.fc2Weights)
        tf.summary.histogram("fcBiases2", self.mdl.fc2Biases)
        print('merge all summaries')
        mergedSummary = tf.summary.merge_all()
        
        # Initialize variables (biases, weights)
        self.sess.run(tf.global_variables_initializer())
        
        
        print('Begin training')
        stepCount = 10 #init with a small number
        self.trainAcc = 0

        for epoch in range(numEpochs):
            
            ##training
            self.sess.run(self.training_init_op) # Reset iterator to training miniBatch

            accHistTrain = []
            accHistTest = []
            lossHistTest = []
         
#            bar = ProgBar('Learning epoch {:2d} of {} in {} steps'.format(epoch+1, numEpochs, stepCount))
            bar = ProgressTrain(self.trainAcc, epoch+1)
            bar.start()
            step = 0
            try:
                while(True):
                   
                    #Calculate our current step
                    progStep = step % (stepCount+1+3)
                    bar.progress(progStep * 100 / stepCount )
                    if step % 2 != 0:
                        
                        # Calculate accuracy
                        # Back propigate using adam optimizer to update weights and biases.
                        acc, _ = self.sess.run([self.mdl.accuracy, self.mdl.trainStep])#ev feed_dict = {self.mdl.isTraining: False}
                        accHistTrain.append(acc)
                        
                    else:
                        
                        # Calculate accuracy
                        # Back propigate using adam optimizer to update weights and biases.
                        # Get Train Summary for one batch and
                        
                        acc, _, summary = self.sess.run([self.mdl.accuracy, self.mdl.trainStep, mergedSummary])
                        accHistTrain.append(acc)
                        
                       
                        
                        # add summary to TensorBoard
                        trainWriter.add_summary(summary, epoch * stepCount + step)
                        trainWriter.flush()
                    
                    step += 1
            except tf.errors.OutOfRangeError:
                pass
            bar.end()
            self.trainAcc = np.mean(accHistTrain)
            print('Training accuracy: {:.3f}'.format(self.trainAcc))
            
            self.confusionMatrix = np.empty(0)
            
            ## Testing
            self.sess.run(self.testing_init_op) # Reset iterator to test miniBatch
            try:
                while(True):
                    acc, loss, confMatrix = self.sess.run([self.mdl.accuracy, self.mdl.loss, 
                                                           self.mdl.confusionMatrix])
                    accHistTest.append(acc)
                    lossHistTest.append(loss)
                    
                    if self.confusionMatrix.size == 0:
                        self.confusionMatrix = confMatrix
                    else:
                        self.confusionMatrix += confMatrix
                                        
            except tf.errors.OutOfRangeError:
                pass
            
            
            
            acc = np.mean(accHistTest)
            loss = np.mean(lossHistTest)
            print("Testing accuracy:  {:.3f}".format(acc))
            print("Testing loss:      {:.3f}".format(loss))
            print("Confusion Matrix:")
            plotter.printConfusionMatrix(self.confusionMatrix)
            
            accSummary = tf.Summary(value=[tf.Summary.Value(tag='Test_Accuracy',simple_value = acc),])
            lossSummary = tf.Summary(value=[tf.Summary.Value(tag='Test_Loss',simple_value = loss),])
            testWriter.add_summary(lossSummary, epoch)
            testWriter.add_summary(accSummary, epoch)
            testWriter.flush()
            
            
            ## Calculate stepCount after first epoch has passed
            if epoch == 0:
                stepCount = step
            
        trainWriter.close()
        testWriter.close()

    def saveModel(self, outputDir):
        print('Save tfModel')
        # prepare checkpoint writer
        self.saver = tf.train.Saver(var_list=tf.global_variables())
        # Save the Model
        if os.path.exists(outputDir+'/weights.ckpt'):
            os.remove(outputDir + '/weights.ckpt')
        self.saver.save(self.sess, outputDir + '/weights.ckpt')
    
    def loadModel(self, inputDir):
        print('Load tfModel')
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        # start session
        self.sess = tf.Session(config=config) 
        self.saver = tf.train.Saver(var_list=tf.global_variables())
        self.saver.restore(self.sess, inputDir + "/weights.ckpt")

    
    def predict(self, xPredict, miniBatchSize):
        #Make some Predictions
        print('starting prediction')
        assert (self.mdl.train == False), 'model graph shouldnt be in train mode!'
        xPl = tf.placeholder(dtype = tf.uint8, shape = xPredict.shape) # placeholder needed to feed large videos
        xPredictTF = tf.data.Dataset.from_tensor_slices({'x': xPl,
                                                         'y': tf.zeros((xPredict.shape[0], 1, 7), dtype=tf.uint8)})
        
        xPredictTF = xPredictTF.batch(miniBatchSize)
        predict_init_op = self.iterator.make_initializer(xPredictTF)
        self.sess.run(predict_init_op, feed_dict = {xPl: xPredict})
        
        yPredict = None
        try:
            yPredict = np.array(self.sess.run(self.mdl.probabillities))
            while(True):
                newVal = np.array(self.sess.run(self.mdl.probabillities))
                yPredict = np.append(yPredict, newVal, axis=0)
        except tf.errors.OutOfRangeError:
            pass
        print('finished prediction')
        return yPredict
    
    def reset(self):
        print("Reset tfModel")
        tf.reset_default_graph()
    
    def __del__(self):
        print("Deleting tfModel")
        tf.reset_default_graph()
        self.sess.close
        del self.mdl
       
