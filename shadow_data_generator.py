import tensorflow as tf
from tensorflow import initializers, reduce_mean
from tensorflow.contrib import slim

model_forward_generator_name = 'ModelX2Y'
model_backward_generator_name = 'ModelY2X'


def _shadowdata_generator_model(netinput, is_training=True):
    with slim.arg_scope(
            [slim.conv2d, slim.conv2d_transpose],
            weights_initializer=initializers.variance_scaling(scale=2.0),
            # weights_regularizer=slim.l2_regularizer(0.001),
            # normalizer_fn=slim.batch_norm,
            # normalizer_params={'is_training': is_training, 'decay': 0.95},
            # normalizer_fn=slim.instance_norm,
            # normalizer_params={'center': True, 'scale': True, 'epsilon': 0.001},
            activation_fn=(lambda inp: slim.nn.leaky_relu(inp)),
            trainable=is_training,
            data_format="NHWC"
    ):
        # netinput = tf.transpose(netinput, [0, 3, 1, 2])
        net = slim.conv2d(netinput, 144, [1, 1])
        net = slim.conv2d(net, 72, [1, 1])
        net = slim.conv2d(net, 36, [1, 1])
        net = slim.conv2d(net, 36, [1, 1])
        net = slim.conv2d(net, 36, [1, 1])
        net = slim.conv2d(net, 72, [1, 1])
        net = slim.conv2d(net, 144, [1, 1])
        # net = tf.transpose(net, [0, 2, 3, 1])
        return net


def _shadowdata_discriminator_model(generated_data, generator_input, is_training=True):
    # bn_training_params = {'is_training': is_training, 'decay': 0.95}
    # normalizer_fn=slim.batch_norm,
    with slim.arg_scope([slim.fully_connected],
                        weights_initializer=initializers.variance_scaling(scale=2.0),
                        # weights_regularizer=slim.l2_regularizer(0.001),
                        # normalizer_fn=slim.batch_norm,
                        # normalizer_params={'is_training': is_training, 'decay': 0.95},
                        # normalizer_fn=slim.instance_norm,
                        # normalizer_params={'center': True, 'scale': True, 'epsilon': 0.001},
                        activation_fn=(lambda inp: slim.nn.leaky_relu(inp))):
        net = tf.concat(axis=3, values=[generated_data, generator_input])

        # net = tf.transpose(net, [0, 3, 1, 2])
        # filter_count = 16
        # net = slim.conv2d(net, filter_count, [1, 1], stride=2)
        # net = slim.conv2d(net, int(filter_count / 2), [1, 1], stride=2)
        # net = slim.conv2d(net, int(filter_count / 4), [1, 1], stride=2)
        # net = slim.conv2d(net, int(filter_count / 8), [1, 1], stride=2)
        # net = slim.conv2d(net, int(filter_count / 16), [1, 1], stride=2)

        net = slim.flatten(net)
        net = slim.fully_connected(net, 192, scope='fc1')
        net = slim.fully_connected(net, 128, scope='fc2')
        net = slim.fully_connected(net, 96, scope='fc3')
        net = slim.fully_connected(net, 64, scope='fc4')
        net = slim.fully_connected(net, 48, scope='fc5')
        net = slim.fully_connected(net, 32, scope='fc6')

    return net


def construct_inference_graph(input_tensor, model_name, clip_invalid_values=True):
    print("clip_invalid_values")
    print(clip_invalid_values)
    shp = input_tensor.get_shape()
    patch_size = shp[0] * shp[1]

    input_tensor = tf.reshape(input_tensor, [patch_size, shp[2]])
    input_tensor_groups = tf.split(axis=0, num_or_size_splits=patch_size, value=input_tensor)
    output_tensor_group = []
    for i in range(patch_size):
        input_tensor = tf.expand_dims(input_tensor_groups[i], [0])
        with tf.variable_scope(model_name):
            with tf.variable_scope('Generator', reuse=tf.AUTO_REUSE):
                input_tensor = tf.expand_dims(input_tensor, [0])
                generated_tensor = _shadowdata_generator_model(input_tensor, False)
                if clip_invalid_values:
                    input_mean = reduce_mean(input_tensor)
                    generated_mean = reduce_mean(generated_tensor)

        if clip_invalid_values:
            result_tensor = tf.cond(tf.less(generated_mean, input_mean),
                                    lambda: generated_tensor,
                                    lambda: input_tensor)
        else:
            result_tensor = generated_tensor

        output_tensor_group.append(tf.squeeze(result_tensor, [0, 1]))

    image_output = tf.concat(output_tensor_group, axis=0)
    image_output = tf.reshape(image_output, [shp[0], shp[1], shp[2]])

    return image_output


def create_generator_restorer():
    # Restore all the variables that were saved in the checkpoint.
    cyclegan_restorer = tf.train.Saver(
        slim.get_variables_to_restore(include=[model_forward_generator_name]) +
        slim.get_variables_to_restore(include=[model_backward_generator_name]), name='GeneratorRestoreHandler'
    )
    return cyclegan_restorer
