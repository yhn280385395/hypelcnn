from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os

import tensorflow as tf
from absl import flags
from tensorflow.contrib.data import shuffle_and_repeat

from DataLoader import SampleSet
from GRSS2013DataLoader import GRSS2013DataLoader
from shadow_data_generator import _shadowdata_generator_model, _shadowdata_discriminator_model

tfgan = tf.contrib.gan
layers = tf.contrib.layers

flags.DEFINE_integer('batch_size', 128 * 20, 'The number of images in each batch.')

flags.DEFINE_string('master', '', 'Name of the TensorFlow master to use.')

flags.DEFINE_string('train_log_dir', os.path.join(os.path.dirname(__file__), 'log'),
                    'Directory where to write event logs.')

flags.DEFINE_float('generator_lr', 0.0002,
                   'The compression model learning rate.')

flags.DEFINE_float('discriminator_lr', 0.0001,
                   'The discriminator learning rate.')

flags.DEFINE_integer('max_number_of_steps', 500000,
                     'The maximum number of gradient steps.')

flags.DEFINE_integer(
    'ps_tasks', 0,
    'The number of parameter servers. If the value is 0, then the parameters '
    'are handled locally by the worker.')

flags.DEFINE_integer(
    'task', 0,
    'The Task ID. This value is used when training with multiple workers to '
    'identify each worker.')

flags.DEFINE_float('cycle_consistency_loss_weight', 10.0,
                   'The weight of cycle consistency loss')

FLAGS = flags.FLAGS


class InitializerHook(tf.train.SessionRunHook):

    def __init__(self, input_itr, normal_placeholder, shadow_placeholder, normal_data, shadow_data):
        self.input_itr = input_itr
        self.shadow_data = shadow_data
        self.normal_data = normal_data
        self.shadow_placeholder = shadow_placeholder
        self.normal_placeholder = normal_placeholder

    def after_create_session(self, session, coord):
        session.run(self.input_itr.initializer,
                    feed_dict={self.shadow_placeholder: self.shadow_data,
                               self.normal_placeholder: self.normal_data})


def load_op(batch_size, iteration_count):
    neighborhood = 0
    loader = GRSS2013DataLoader('C:/GoogleDriveBack/PHD/Tez/Source')
    data_set = loader.load_data(neighborhood, )

    shadow_map, shadow_ratio = loader._load_shadow_map(neighborhood, data_set.concrete_data[:, :,
                                                                     0:data_set.concrete_data.shape[2] - 1])

    # normal_data_as_matrix, shadow_data_as_matrix = GRSS2013DataLoader.get_targetbased_shadowed_normal_data(data_set,
    #                                                                                     loader,
    #                                                                                     shadow_map,
    #                                                                                     loader.load_samples(0.1))

    normal_data_as_matrix, shadow_data_as_matrix = get_data_from_scene(data_set, loader, shadow_map)

    # normal_data_as_matrix, shadow_data_as_matrix = GRSS2013DataLoader.get_all_shadowed_normal_data(
    #     data_set,
    #     loader,
    #     shadow_map)

    normal_data_as_matrix = normal_data_as_matrix[:, :, :, 0:normal_data_as_matrix.shape[3] - 1]
    shadow_data_as_matrix = shadow_data_as_matrix[:, :, :, 0:shadow_data_as_matrix.shape[3] - 1]

    normal = tf.placeholder(dtype=normal_data_as_matrix.dtype, shape=normal_data_as_matrix.shape, name='x')
    shadow = tf.placeholder(dtype=shadow_data_as_matrix.dtype, shape=shadow_data_as_matrix.shape, name='y')

    epoch = int((iteration_count * batch_size) / normal_data_as_matrix.shape[0])
    data_set = tf.data.Dataset.from_tensor_slices((normal, shadow)).apply(
        shuffle_and_repeat(buffer_size=10000, count=epoch)).batch(batch_size)
    data_set_itr = data_set.make_initializable_iterator()

    return InitializerHook(data_set_itr, normal, shadow, normal_data_as_matrix, shadow_data_as_matrix)


def get_data_from_scene(data_set, loader, shadow_map):
    samples = SampleSet(training_targets=loader.read_targets("\\shadow_cycle_gan\\result_raw_941.tif"),
                        test_targets=None,
                        validation_targets=None)
    firstMarginStart = 5
    firstMarginEnd = data_set.concrete_data.shape[0] - 5
    secondMarginStart = 5
    secondMarginEnd = data_set.concrete_data.shape[1] - 5
    for target_index in range(0, samples.training_targets.shape[0]):
        current_target = samples.training_targets[target_index]
        if not (firstMarginStart < current_target[1] < firstMarginEnd and
                secondMarginStart < current_target[0] < secondMarginEnd):
            current_target[2] = -1
    normal_data_as_matrix, shadow_data_as_matrix = GRSS2013DataLoader.get_targetbased_shadowed_normal_data(data_set,
                                                                                                           loader,
                                                                                                           shadow_map,
                                                                                                           samples)
    return normal_data_as_matrix, shadow_data_as_matrix


def _define_model(images_x, images_y):
    """Defines a CycleGAN model that maps between images_x and images_y.

    Args:
      images_x: A 4D float `Tensor` of NHWC format.  Images in set X.
      images_y: A 4D float `Tensor` of NHWC format.  Images in set Y.

    Returns:
      A `CycleGANModel` namedtuple.
    """
    cyclegan_model = tfgan.cyclegan_model(
        generator_fn=_shadowdata_generator_model,
        discriminator_fn=_shadowdata_discriminator_model,
        data_x=images_x,
        data_y=images_y)

    # Add summaries for generated images.
    # tfgan.eval.add_cyclegan_image_summaries(cyclegan_model)

    return cyclegan_model


def _get_lr(base_lr):
    """Returns a learning rate `Tensor`.

    Args:
      base_lr: A scalar float `Tensor` or a Python number.  The base learning
          rate.

    Returns:
      A scalar float `Tensor` of learning rate which equals `base_lr` when the
      global training step is less than FLAGS.max_number_of_steps / 2, afterwards
      it linearly decays to zero.
    """
    global_step = tf.train.get_or_create_global_step()
    lr_constant_steps = FLAGS.max_number_of_steps // 2

    def _lr_decay():
        return tf.train.polynomial_decay(
            learning_rate=base_lr,
            global_step=(global_step - lr_constant_steps),
            decay_steps=(FLAGS.max_number_of_steps - lr_constant_steps),
            end_learning_rate=0.0)

    return tf.cond(global_step < lr_constant_steps, lambda: base_lr, _lr_decay)


def _get_optimizer(gen_lr, dis_lr):
    """Returns generator optimizer and discriminator optimizer.

    Args:
      gen_lr: A scalar float `Tensor` or a Python number.  The Generator learning
          rate.
      dis_lr: A scalar float `Tensor` or a Python number.  The Discriminator
          learning rate.

    Returns:
      A tuple of generator optimizer and discriminator optimizer.
    """
    # beta1 follows
    # https://github.com/junyanz/CycleGAN/blob/master/options.lua
    gen_opt = tf.train.AdamOptimizer(gen_lr, beta1=0.5, use_locking=True)
    dis_opt = tf.train.AdamOptimizer(dis_lr, beta1=0.5, use_locking=True)
    return gen_opt, dis_opt


def _define_train_ops(cyclegan_model, cyclegan_loss):
    """Defines train ops that trains `cyclegan_model` with `cyclegan_loss`.

    Args:
      cyclegan_model: A `CycleGANModel` namedtuple.
      cyclegan_loss: A `CycleGANLoss` namedtuple containing all losses for
          `cyclegan_model`.

    Returns:
      A `GANTrainOps` namedtuple.
    """
    gen_lr = _get_lr(FLAGS.generator_lr)
    dis_lr = _get_lr(FLAGS.discriminator_lr)
    gen_opt, dis_opt = _get_optimizer(gen_lr, dis_lr)

    train_ops = tfgan.gan_train_ops(
        cyclegan_model,
        cyclegan_loss,
        generator_optimizer=gen_opt,
        discriminator_optimizer=dis_opt,
        summarize_gradients=True,
        colocate_gradients_with_ops=True,
        check_for_unused_update_ops=False,
        aggregation_method=tf.AggregationMethod.EXPERIMENTAL_ACCUMULATE_N)

    tf.summary.scalar('generator_lr', gen_lr)
    tf.summary.scalar('discriminator_lr', dis_lr)
    return train_ops


def main(_):
    if not tf.gfile.Exists(FLAGS.train_log_dir):
        tf.gfile.MakeDirs(FLAGS.train_log_dir)

    with tf.device(tf.train.replica_device_setter(FLAGS.ps_tasks)):
        with tf.name_scope('inputs'):
            initializer_hook = load_op(FLAGS.batch_size, FLAGS.max_number_of_steps)
            training_input_iter = initializer_hook.input_itr
            images_x, images_y = training_input_iter.get_next()
            # Set batch size for summaries.
            # images_x.set_shape([FLAGS.batch_size, None, None, None])
            # images_y.set_shape([FLAGS.batch_size, None, None, None])

        # Define CycleGAN model.
        cyclegan_model = _define_model(images_x, images_y)

        # Define CycleGAN loss.
        cyclegan_loss = tfgan.cyclegan_loss(
            cyclegan_model,
            cycle_consistency_loss_weight=FLAGS.cycle_consistency_loss_weight,
            tensor_pool_fn=tfgan.features.tensor_pool)

        # Define CycleGAN train ops.
        train_ops = _define_train_ops(cyclegan_model, cyclegan_loss)

        # Training
        train_steps = tfgan.GANTrainSteps(1, 1)
        status_message = tf.string_join(
            [
                'Starting train step: ',
                tf.as_string(tf.train.get_or_create_global_step())
            ],
            name='status_message')
        if not FLAGS.max_number_of_steps:
            return
        tfgan.gan_train(
            train_ops,
            FLAGS.train_log_dir,
            save_checkpoint_secs=120,
            get_hooks_fn=tfgan.get_sequential_train_hooks(train_steps),
            hooks=[
                initializer_hook,
                tf.train.StopAtStepHook(num_steps=FLAGS.max_number_of_steps),
                tf.train.LoggingTensorHook([status_message], every_n_iter=10)
            ],
            master=FLAGS.master,
            is_chief=FLAGS.task == 0)


if __name__ == '__main__':
    # tf.flags.mark_flag_as_required('image_set_x_file_pattern')
    # tf.flags.mark_flag_as_required('image_set_y_file_pattern')
    tf.app.run()
