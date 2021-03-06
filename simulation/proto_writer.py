# Generate solver prototxts and corresponding train_val prototxts.
# Takes input R Gaussian std sweep range, and D sweep depth
import os
import caffe
import numpy as np
import itertools
import math
from google.protobuf import text_format as proto
from caffe.proto import caffe_pb2
caffe.set_mode_gpu()
# initialization

def snr_sweep(gaussian_param_range, g_intvl, uniform_param_range, 
		q_intvl, depth, template="../prototxt/train/origin/goog_train_val.prototxt"):
	"""
	Given range of parameters and depth, generate the sweeping prototxts and write
	them to given save path. Note that noise params are given in SNR dBs.
	Returns the list of names of generated prototxts. Note that SNR values for
	gaussian noise layers are hold still, with variations on uniform noise layers
	"""
	train_net = caffe_pb2.NetParameter()
	proto.Merge((open(template).read()), train_net)
	net = caffe.Net(template, '../models/googlenet/googlenet.caffemodel', 
		caffe.TRAIN)
	net.forward()
	# Next enumerate the sweep range
	uniform_param_array = np.arange(uniform_param_range[0], 
		uniform_param_range[1], q_intvl)
	gaussian_param_array = np.arange(gaussian_param_range[0], 
		gaussian_param_range[1], g_intvl)
	param_list, name_list = [], []
	for q_param in uniform_param_array:
		for g_param in gaussian_param_array:
			param_list.append([q_param] + [g_param] * depth)
	for params in param_list:
		file_name = os.path.join("../prototxt/train/redeye/", 
			"goog_train" + str(params).replace(' ', 
				'').replace('[','_').replace(']','').replace(',','_')
			 + ".prototxt")
		_write_prototxt(train_net, params, file_name, depth, net.blobs)
		name_list.append(file_name)
	del(net)
	return name_list

def snr_data_sweep(data_snr_range, intvl, gamma, noise_type, 
	template='../prototxt/train/origin/goog_train_val.prototxt'):
	"""
	Given interval and range for gaussian noise, insert those into data layer
	"""
	tmp_net = caffe_pb2.NetParameter()
	proto.Merge((open(template).read()), tmp_net)
	net = caffe.Net(template, '../models/googlenet/googlenet.caffemodel', 
		caffe.TRAIN)
	net.forward()
	# Next enumerate the sweep range
	name_list = []
	for snr in data_snr_range:
		for n in tmp_net.layer:
			if str(n.type) == "Noise" and str(n.bottom[0]) == "data":
				if noise_type == "uniform":
					param = _scale_uniform_param(snr, net.blobs['data'].data)
					n.noise_param.uniform_param.min_u = -param
					n.noise_param.uniform_param.max_u = param
				if noise_type == "gaussian":
					n.noise_param.gaussian_param.stddev = _scale_gaussian_param(snr, 
						net.blobs['data'].data)
			elif str(n.type) == "Data" and n.include[0].phase == 1:
				n.transform_param.gamma = gamma
			else:
				n = n
		proto_name = os.path.join("../prototxt/train/redeye/", 
			"goog_train_data_" + str(snr) + ".prototxt")
		name_list.append(proto_name)
		modified_proto = proto.MessageToString(tmp_net)
		with open(proto_name, 'w') as template:
		 	template.write(modified_proto)

	del(net)
	return name_list


def snr_full_sweep(gaussian_param_range, g_intvl, uniform_param_range, 
		q_intvl, depth, template="../prototxt/train/origin/goog_train_val.prototxt"):
	"""
	Given range of parameters and depth, generate the sweeping prototxts and write
	them to given save path. Note that noise params are given in SNR dBs.
	Returns the list of names of generated prototxts.
	"""
	train_net = caffe_pb2.NetParameter()
	proto.Merge((open(template).read()), train_net)
	net = caffe.Net(template, '../models/googlenet/googlenet.caffemodel', 
		caffe.TRAIN)
	net.forward() 
	# Next enumerate the sweep range
	uniform_param_array = np.arange(uniform_param_range[0], 
		uniform_param_range[1], q_intvl)
	range_list = [uniform_param_array]
	for i in range(depth):
		range_list.append(np.arange(gaussian_param_range[0], 
			gaussian_param_range[1], g_intvl))
	param_list = list(itertools.product(*range_list))
	name_list = []
	for params in param_list:
		file_name = os.path.join("../prototxt/train/redeye/", 
			"goog_train" + str(params).replace(' ', 
				'').replace('(','_').replace(')','').replace(',','_')
			 + ".prototxt")
		_write_prototxt(train_net, params, file_name, depth, net.blobs)
		name_list.append(file_name)
	del(net)
	return name_list

def _write_prototxt(train_net, param_list, file_name, depth, blob):
	"""
	Given a list of parameters with length (depth + 1), insert noise with given 
	parameters to the prototext given and write to redeye directory with given 
	file name. 
	"""
	if os.path.isfile(file_name):
		return
	extra_layers = []
	new_train_net = caffe_pb2.NetParameter()
	# Has to modify on the new one, while search old layer names from old net
	new_train_net.CopyFrom(train_net)
	for layer in train_net.layer:
		# scan from the bottom layers
		for bottom_name in layer.bottom:
			if bottom_name != "label" and layer.type != "Silence" and layer.type != "Gamma":
				bottom_layer = _get_layer_by_name(bottom_name, train_net.layer)
				if  bottom_layer.type == "Convolution" and layer.type != "ReLU":
					if depth > 0:
						noise_layer = _get_noise_layer(bottom_name, 
							"gaussian", param_list[depth], blob)
						new_layers = _layer_mutation(bottom_layer, noise_layer, 
							[_get_layer_by_name(layer.name, new_train_net.layer)]) 
						extra_layers.extend(new_layers)
						if bottom_name == layer.bottom[-1] and \
							layer.type != "InnerProduct":
							depth -= 1
					# top layers should be modified already
				if (bottom_layer.type == "Pooling" and \
					len(bottom_layer.top) > 1) or bottom_layer.type == "Concat":
					if depth == 0:
						noise_layer = _get_noise_layer(bottom_name, 
							"uniform", param_list[depth], blob)
						new_layers = _layer_mutation(bottom_layer, noise_layer, 
							_get_shared_bottom_tops(_get_layer_by_name(layer.name, 
								train_net.layer), new_train_net.layer))
						extra_layers.extend(new_layers)
						if bottom_name == layer.bottom[-1] and \
							layer.type != "InnerProduct":
							depth -= 1
		# for fully connected layers, append noise layer at the bottom
		if depth >= 0:
			if layer.type == "InnerProduct" and "fc" in layer.name:
				# To filter out the second fc classifier layer
				bottom_layer = _get_layer_by_name(layer.bottom[0], train_net.layer)
				noise_layer = _get_noise_layer(layer.bottom[0], "uniform",
					param_list[0], blob)
				new_layers = _layer_mutation(bottom_layer, noise_layer, 
					[_get_layer_by_name(layer.name, new_train_net.layer)])
				extra_layers.extend(new_layers)
	
	# next arrange layers into correct positions
	new_layers = _insert_noise_layers(extra_layers, new_train_net.layer)
	_mute_noise_output(extra_layers, new_layers)
	# Now write out the generated new prototxt
	new_net = caffe_pb2.NetParameter(name="NoisyGoogleNet_" + str(param_list), 
		layer=new_layers)
	prototxt = proto.MessageToString(new_net)
	with open(file_name, 'w') as new_proto:
		new_proto.write(prototxt)

def _mute_noise_output(noise_layers, net_layers):
	"""
	Insert silence layers to mute outputs from the noise parameter top layers.
	"""
	silence_layer = caffe_pb2.LayerParameter(type="Silence", name="MuteNoise", 
		bottom=[n.top[1] for n in noise_layers])
	net_layers.append(silence_layer)

def _insert_noise_layers(new_layers, layers):
	"""
	Given a net of layers, replace the old layers with given modified new layers, and 
	insert generated new layers to the net based on bottom and top order.
	Returns the new net.
	"""
	sorted_layers = []
	sorted_layers.extend(layers)
	islice = []
	# insert noise layers into proper positions
	for n in new_layers:
		# each iteration index will be regenerated to stay in right order
		for idx, l in enumerate(sorted_layers):
			if n.top[0] in l.bottom and l.type != "ReLU":
				islice.append((idx, n))
	for i in range(len(islice)):
		sorted_layers.insert(islice[i][0] + i, islice[i][1])
	return sorted_layers

def _get_shared_bottom_tops(top, layers):
	"""
	Get the layers that have the same bottom layer as given top layer's.
	This happens for most pooling layers and all concat layers, where
	outputs are branched to several convolution layers on top.
	"""
	tops = []
	for l in layers:
		if set(top.bottom).intersection(l.bottom) and l.type != "Noise":
			tops.append(l)
	return tops

def _get_layer_by_name(name, layers):
	"""
	Given NetParameter.net and name of the layer, return the LayerParameter
	"""
	for l in layers:
		if l.name == name:
			return l

def _get_noise_layer(layer_name, noise_type, raw_param, net_blobs):
	"""
	Given noise type and parameters, generate the Noise LayerParameter by
	scaling the given raw parameters.
	"""
	pool = net_blobs[layer_name].data
	if noise_type == "gaussian":
		param = _scale_gaussian_param(raw_param, pool)
		return _construct_noise_layer(_construct_gaussian_noise(0, param))
	if noise_type == "uniform":
		param = _scale_uniform_param(raw_param, pool)
		return _construct_noise_layer(_construct_uniform_noise(-param, param))

def _get_top_layers(bottom, layers):
	"""
	Given list of LayerParemeters, get the top layers of current bottom layer
	"""
	top = []
	for l in layers:
		for t in bottom.top:
			if str(t) == str(l.name):
				top.append(l)
	return top

def _get_bottom_layers(top, layers):
	"""
	Given list of LayerParemeters, get the bottom layers of current top layer
	"""
	bottom = []
	for l in layers:
		for b in top.bottom:
			if str(b) == str(l.name):
				bottom.append(l)
	return bottom

def _layer_mutation(bottom, extra, top):
	"""
	Add noise after given single bottom layer and feed to top layer.
	The extra added layer does not need to have bottom/top/name assigned for input.
	The bottom is a list of layers, while top is one layer.
	Returns the new extra layers, and modified the top layers
	"""
	extra_layers = []
	for t in top:
		x = caffe_pb2.LayerParameter()
		x.CopyFrom(extra)
		x.bottom.extend(bottom.top)
		x.name = str(bottom.name) + '_noise_' + str(t.name)
		x.top.append(x.name)
		x.top.append(x.name + "_param")

		for i, l in enumerate(bottom.top):
			if l in t.bottom:
				t.bottom.remove(l)
				t.bottom.extend([x.top[i]])
 		extra_layers.append(x)
	return extra_layers

def _scale_gaussian_param(snr, data):
	"""
	A helper function to convert given gaussian parameters in SNR dB 
	according to standard deviation, and scale to correct values 
	according to given data set features.
	"""
	return math.sqrt(data.std() ** 2 / math.pow(10, snr / 10.0))

def _scale_uniform_param(snr, data):
	"""
	A helper function to convert given uniform parameters in SNR dB according
	to desired standard deviation, and scale to correct values according 
	to given data set features.
	"""
	return math.sqrt(3 * data.std()**2 / math.pow(10, snr / 10.0))

def _construct_noise_layer(noise_param):
	"""
	Generate the Noise LayerParemeter given NoiseParameter
	"""
	return caffe_pb2.LayerParameter(type="Noise", noise_param=noise_param)

def _construct_gaussian_noise(mean, stddev, is_pass=1, 
	min_sd=0.0, max_sd=255.0, scale=1.0, ds=1.0):
	"""
	Given mean and standard deviation, generate NoiseParameter
	"""
	gNoise = caffe_pb2.GaussianNoiseParameter(mean=mean, stddev=stddev, 
		min_sd=min_sd, max_sd=max_sd, scale=scale)
	return caffe_pb2.NoiseParameter(ntype=0, forward_only=is_pass, 
		gaussian_param=gNoise, diff_scale=ds)

def _construct_uniform_noise(minimum, maximum, 
	is_pass=1, scale=1.0, ds=1.0):
	"""
	Given uniform random range for uniform noise error, generate NoiseParameter
	"""
	qNoise = caffe_pb2.UniformNoiseParameter(min_u=minimum, max_u=maximum, scale=scale)
	return caffe_pb2.NoiseParameter(ntype=2, forward_only=is_pass, 
		uniform_param=qNoise, diff_scale=ds)

def _construct_poisson_noise(l, is_pass=1, norm=255.0, scale=1.0, ds=1.0):
	"""
	Given lambda for photon arrival estimation on physical image sensor, 
	generate NoiseParameter
	"""
	pNoise = caffe_pb2.PoissonNoiseParameter(_lambda=l, 
		norm=norm, scale=scale)
	return caffe_pb2.NoiseParameter(ntype=1, 
		forward_only=is_pass, poisson_param=pNoise, diff_scale=ds)

#_write_prototxt((1,2,3), "../prototxt/train/origin/goog_train_val.prototxt", 
# 	"./try.prototxt", depth=2)
# snr_sweep((20,21), 1, (20,21), 1, 5)
# print sweep((-10, 10), 2, (2, 4), 1, 1)
