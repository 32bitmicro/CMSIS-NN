# SPDX-FileCopyrightText: Copyright 2010-2024 Arm Limited and/or its affiliates <open-source-office@arm.com>
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the License); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an AS IS BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import sys
import json
import math
import subprocess
import keras

from abc import ABC, abstractmethod
from packaging import version

import numpy as np
import tensorflow as tf
import keras

class TestSettings(ABC):

    # This is the generated test data used by the test cases.
    OUTDIR = 'TestCases/TestData/'

    # This is input to the data generation. If everything or something is regenerated then it is overwritten.
    # So it always has the same data as the OUTDIR.
    # The purpose of the pregen is primarily for debugging, as it is enabling to change a single parameter and see how
    # output changes (or not changes), without regenerating all input data.
    # It also convinient when testing changes in the script, to be able to run all test sets again.
    PREGEN = 'PregeneratedData/'

    INT32_MAX = 2147483647
    INT32_MIN = -2147483648
    INT64_MAX = 9223372036854775807
    INT64_MIN = -9223372036854775808
    INT16_MAX = 32767
    INT16_MIN = -32768
    INT8_MAX = 127
    INT8_MIN = -128
    INT4_MAX = 7
    INT4_MIN = -8

    REQUIRED_MINIMUM_TENSORFLOW_VERSION = version.parse("2.10")

    CLANG_FORMAT = 'clang-format-12 -i'  # For formatting generated headers.

    def __init__(self,
                 dataset,
                 testtype,
                 regenerate_weights,
                 regenerate_input,
                 regenerate_biases,
                 schema_file,
                 in_ch,
                 out_ch,
                 x_in,
                 y_in,
                 w_x,
                 w_y,
                 stride_x=1,
                 stride_y=1,
                 pad=False,
                 randmin=np.iinfo(np.dtype('int8')).min,
                 randmax=np.iinfo(np.dtype('int8')).max,
                 batches=1,
                 generate_bias=True,
                 relu6=False,
                 out_activation_min=None,
                 out_activation_max=None,
                 int16xint8=False,
                 bias_min=np.iinfo(np.dtype('int32')).min,
                 bias_max=np.iinfo(np.dtype('int32')).max,
                 dilation_x=1,
                 dilation_y=1,
                 interpreter="tensorflow",
                 int4_weights=False):

        self.int4_weights = int4_weights

        if self.INT8_MIN != np.iinfo(np.dtype('int8')).min or self.INT8_MAX != np.iinfo(np.dtype('int8')).max or \
           self.INT16_MIN != np.iinfo(np.dtype('int16')).min or self.INT16_MAX != np.iinfo(np.dtype('int16')).max or \
           self.INT32_MIN != np.iinfo(np.dtype('int32')).min or self.INT32_MAX != np.iinfo(np.dtype('int32')).max:
            raise RuntimeError("Unexpected int min/max error")

        self.use_tflite_micro_interpreter = False

        if interpreter == "tflite_runtime":
            from tflite_runtime.interpreter import Interpreter
            from tflite_runtime.interpreter import OpResolverType
            import tflite_runtime as tfl_runtime

            revision = tfl_runtime.__git_version__
            version = tfl_runtime.__version__
            interpreter = "tflite_runtime"

        elif interpreter == "tensorflow":
            from tensorflow.lite.python.interpreter import Interpreter
            from tensorflow.lite.python.interpreter import OpResolverType

            revision = tf.__git_version__
            version = tf.__version__
            interpreter = "tensorflow"

        elif interpreter == "tflite_micro":
            from tensorflow.lite.python.interpreter import Interpreter
            from tensorflow.lite.python.interpreter import OpResolverType

            import tflite_micro
            self.tflite_micro = tflite_micro
            self.use_tflite_micro_interpreter = True

            revision = None
            version = tflite_micro.__version__
            interpreter = "tflite_micro"
        else:
            raise RuntimeError(f"Invalid interpreter {interpreter}")

        self.Interpreter = Interpreter
        self.OpResolverType = OpResolverType

        self.tensorflow_reference_version = (
            "// Generated by {} using tensorflow version {} (Keras version {}).\n".format(
                os.path.basename(__file__), tf.__version__, keras.__version__))

        self.tensorflow_reference_version += ("// Interpreter from {} version {} and revision {}.\n".format(
            interpreter, version, revision))

        # Randomization interval
        self.mins = randmin
        self.maxs = randmax

        self.bias_mins = bias_min
        self.bias_maxs = bias_max

        self.input_ch = in_ch
        self.output_ch = out_ch
        self.x_input = x_in
        self.y_input = y_in
        self.filter_x = w_x
        self.filter_y = w_y
        self.stride_x = stride_x
        self.stride_y = stride_y
        self.dilation_x = dilation_x
        self.dilation_y = dilation_y
        self.batches = batches
        self.test_type = testtype
        self.has_padding = pad

        self.is_int16xint8 = int16xint8

        if relu6:
            self.out_activation_max = 6
            self.out_activation_min = 0
        else:
            if out_activation_min is not None:
                self.out_activation_min = out_activation_min
            else:
                self.out_activation_min = self.INT16_MIN if self.is_int16xint8 else self.INT8_MIN
            if out_activation_max is not None:
                self.out_activation_max = out_activation_max
            else:
                self.out_activation_max = self.INT16_MAX if self.is_int16xint8 else self.INT8_MAX

        # Bias is optional.
        self.generate_bias = generate_bias

        self.generated_header_files = []
        self.pregenerated_data_dir = self.PREGEN

        self.config_data = "config_data.h"

        self.testdataset = dataset

        self.kernel_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'kernel.txt'
        self.inputs_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'input.txt'
        self.bias_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'bias.txt'

        if self.has_padding:
            self.padding = 'SAME'
        else:
            self.padding = 'VALID'

        self.regenerate_new_weights = regenerate_weights
        self.regenerate_new_input = regenerate_input
        self.regenerate_new_bias = regenerate_biases
        self.schema_file = schema_file

        self.headers_dir = self.OUTDIR + self.testdataset + '/'
        os.makedirs(self.headers_dir, exist_ok=True)

        self.model_path = "{}model_{}".format(self.headers_dir, self.testdataset)
        self.model_path_tflite = self.model_path + '.tflite'

        self.input_data_file_prefix = "input"
        self.weight_data_file_prefix = "weights"
        self.bias_data_file_prefix = "biases"
        self.output_data_file_prefix = "output_ref"

    def save_multiple_dim_array_in_txt(self, file, data):
        header = ','.join(map(str, data.shape))
        np.savetxt(file, data.reshape(-1, data.shape[-1]), header=header, delimiter=',')

    def load_multiple_dim_array_from_txt(self, file):
        with open(file) as f:
            shape = list(map(int, next(f)[1:].split(',')))
            data = np.genfromtxt(f, delimiter=',').reshape(shape)
        return data.astype(np.float32)

    def convert_tensor_np(self, tensor_in, converter, *qminmax):
        w = tensor_in.numpy()
        shape = w.shape
        w = w.ravel()
        if len(qminmax) == 2:
            fw = converter(w, qminmax[0], qminmax[1])
        else:
            fw = converter(w)
        fw.shape = shape
        return tf.convert_to_tensor(fw)

    def convert_tensor(self, tensor_in, converter, *qminmax):
        w = tensor_in.numpy()
        shape = w.shape
        w = w.ravel()
        normal = np.array(w)
        float_normal = []

        for i in normal:
            if len(qminmax) == 2:
                float_normal.append(converter(i, qminmax[0], qminmax[1]))
            else:
                float_normal.append(converter(i))

        np_float_array = np.asarray(float_normal)
        np_float_array.shape = shape

        return tf.convert_to_tensor(np_float_array)

    def get_randomized_data(self, dims, npfile, regenerate, decimals=0, minrange=None, maxrange=None):
        if not minrange:
            minrange = self.mins
        if not maxrange:
            maxrange = self.maxs
        if not os.path.exists(npfile) or regenerate:
            regendir = os.path.dirname(npfile)
            os.makedirs(regendir, exist_ok=True)
            if decimals == 0:
                data = tf.Variable(tf.random.uniform(dims, minval=minrange, maxval=maxrange, dtype=tf.dtypes.int64))
                data = tf.cast(data, dtype=tf.float32)
            else:
                data = tf.Variable(tf.random.uniform(dims, minval=minrange, maxval=maxrange, dtype=tf.dtypes.float32))
                data = np.around(data.numpy(), decimals)
                data = tf.convert_to_tensor(data)

            print("Saving data to {}".format(npfile))
            self.save_multiple_dim_array_in_txt(npfile, data.numpy())
        else:
            print("Loading data from {}".format(npfile))
            data = tf.convert_to_tensor(self.load_multiple_dim_array_from_txt(npfile))
        return data

    def get_randomized_input_data(self, input_data, input_shape=None):
        # Generate or load saved input data unless hardcoded data provided
        if input_shape is None:
            input_shape = [self.batches, self.y_input, self.x_input, self.input_ch]
        if input_data is not None:
            input_data = tf.reshape(input_data, input_shape)
        else:
            input_data = self.get_randomized_data(input_shape,
                                                  self.inputs_table_file,
                                                  regenerate=self.regenerate_new_input)
        return input_data

    def get_randomized_bias_data(self, biases):
        # Generate or load saved bias data unless hardcoded data provided
        if not self.generate_bias:
            biases = tf.reshape(np.full([self.output_ch], 0), [self.output_ch])
        elif biases is not None:
            biases = tf.reshape(biases, [self.output_ch])
        else:
            biases = self.get_randomized_data([self.output_ch],
                                              self.bias_table_file,
                                              regenerate=self.regenerate_new_bias,
                                              minrange=self.bias_mins,
                                              maxrange=self.bias_maxs)
        return biases

    def format_output_file(self, file):
        command_list = self.CLANG_FORMAT.split(' ')
        command_list.append(file)
        try:
            process = subprocess.run(command_list)
            if process.returncode != 0:
                print(f"ERROR: {command_list = }")
                sys.exit(1)
        except Exception as e:
            raise RuntimeError(f"{e} from: {command_list = }")

    def write_c_header_wrapper(self):
        filename = "test_data.h"
        filepath = self.headers_dir + filename

        print("Generating C header wrapper {}...".format(filepath))
        with open(filepath, 'w+') as f:
            f.write(self.tensorflow_reference_version)
            while len(self.generated_header_files) > 0:
                f.write('#include "{}"\n'.format(self.generated_header_files.pop()))
        self.format_output_file(filepath)

    def write_common_config(self, f, prefix):
        """
        Shared by conv/depthwise_conv and pooling
        """
        f.write("#define {}_FILTER_X {}\n".format(prefix, self.filter_x))
        f.write("#define {}_FILTER_Y {}\n".format(prefix, self.filter_y))
        f.write("#define {}_STRIDE_X {}\n".format(prefix, self.stride_x))
        f.write("#define {}_STRIDE_Y {}\n".format(prefix, self.stride_y))
        f.write("#define {}_PAD_X {}\n".format(prefix, self.pad_x))
        f.write("#define {}_PAD_Y {}\n".format(prefix, self.pad_y))
        f.write("#define {}_OUTPUT_W {}\n".format(prefix, self.x_output))
        f.write("#define {}_OUTPUT_H {}\n".format(prefix, self.y_output))

    def write_c_common_header(self, f):
        f.write(self.tensorflow_reference_version)
        f.write("#pragma once\n")

    def write_c_config_header(self, write_common_parameters=True) -> None:
        filename = self.config_data

        self.generated_header_files.append(filename)
        filepath = self.headers_dir + filename

        prefix = self.testdataset.upper()

        print("Writing C header with config data {}...".format(filepath))
        with open(filepath, "w+") as f:
            self.write_c_common_header(f)
            if (write_common_parameters):
                f.write("#define {}_OUT_CH {}\n".format(prefix, self.output_ch))
                f.write("#define {}_IN_CH {}\n".format(prefix, self.input_ch))
                f.write("#define {}_INPUT_W {}\n".format(prefix, self.x_input))
                f.write("#define {}_INPUT_H {}\n".format(prefix, self.y_input))
                f.write("#define {}_DST_SIZE {}\n".format(
                    prefix, self.x_output * self.y_output * self.output_ch * self.batches))
                f.write("#define {}_INPUT_SIZE {}\n".format(prefix, self.x_input * self.y_input * self.input_ch))
                f.write("#define {}_OUT_ACTIVATION_MIN {}\n".format(prefix, self.out_activation_min))
                f.write("#define {}_OUT_ACTIVATION_MAX {}\n".format(prefix, self.out_activation_max))
                f.write("#define {}_INPUT_BATCHES {}\n".format(prefix, self.batches))
        self.format_output_file(filepath)

    def get_data_file_name_info(self, name_prefix) -> (str, str):
        filename = name_prefix + "_data.h"
        filepath = self.headers_dir + filename
        return filename, filepath

    def generate_c_array(self, name, array, datatype="int8_t", const="const ", pack=False) -> None:
        w = None

        if type(array) is list:
            w = array
            size = len(array)
        elif type(array) is np.ndarray:
            w = array
            w = w.ravel()
            size = w.size
        else:
            w = array.numpy()
            w = w.ravel()
            size = tf.size(array)

        if pack:
            size = (size // 2) + (size % 2)

        filename, filepath = self.get_data_file_name_info(name)
        self.generated_header_files.append(filename)

        print("Generating C header {}...".format(filepath))
        with open(filepath, "w+") as f:
            self.write_c_common_header(f)
            f.write("#include <stdint.h>\n\n")
            if size > 0:
                f.write(const + datatype + " " + self.testdataset + '_' + name + "[%d] =\n{\n" % size)
                for i in range(size - 1):
                    f.write("  %d,\n" % w[i])
                f.write("  %d\n" % w[size - 1])
                f.write("};\n")
            else:
                f.write(const + datatype + " *" + self.testdataset + '_' + name + " = NULL;\n")
        self.format_output_file(filepath)

    def calculate_padding(self, x_output, y_output, x_input, y_input):
        if self.has_padding:
            # Take dilation into account.
            filter_x = (self.filter_x - 1) * self.dilation_x + 1
            filter_y = (self.filter_y - 1) * self.dilation_y + 1

            pad_along_width = max((x_output - 1) * self.stride_x + filter_x - x_input, 0)
            pad_along_height = max((y_output - 1) * self.stride_y + filter_y - y_input, 0)

            pad_top = pad_along_height // 2
            pad_left = pad_along_width // 2
            pad_top_offset = pad_along_height % 2
            pad_left_offset = pad_along_width % 2

            self.pad_y_with_offset = pad_top + pad_top_offset
            self.pad_x_with_offset = pad_left + pad_left_offset
            self.pad_x = pad_left
            self.pad_y = pad_top
        else:
            self.pad_x = 0
            self.pad_y = 0
            self.pad_y_with_offset = 0
            self.pad_x_with_offset = 0

    @abstractmethod
    def generate_data(self, input_data=None, weights=None, biases=None) -> None:
        ''' Must be overriden '''

    def quantize_scale(self, scale):
        significand, shift = math.frexp(scale)
        significand_q31 = round(significand * (1 << 31))
        return significand_q31, shift

    def get_calib_data_func(self, n_inputs, shape):

        def representative_data_gen():
            representative_testsets = []
            if n_inputs > 0:
                for i in range(n_inputs):
                    representative_testsets.append(np.ones(shape, dtype=np.float32))
                yield representative_testsets
            else:
                raise RuntimeError("Invalid number of representative test sets: {}. Must be more than 0".format(
                    self.test_type))

        return representative_data_gen

    def convert_and_interpret(self, model, inttype, input_data=None, dataset_shape=None):
        """
        Compile and convert a model to Tflite format, run interpreter and allocate tensors.
        """
        self.convert_model(model, inttype, dataset_shape)
        return self.interpret_model(input_data, inttype)

    def convert_model(self, model, inttype, dataset_shape=None, int16x8_int32bias=False):
        model.compile(loss=keras.losses.categorical_crossentropy,
                      metrics=['accuracy'])
        n_inputs = len(model.inputs)

        if dataset_shape:
            representative_dataset_shape = dataset_shape
        else:
            representative_dataset_shape = (self.batches, self.y_input, self.x_input, self.input_ch)

        converter = tf.lite.TFLiteConverter.from_keras_model(model)

        representative_dataset = self.get_calib_data_func(n_inputs, representative_dataset_shape)

        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.representative_dataset = representative_dataset
        converter._experimental_disable_per_channel_quantization_for_dense_layers = True

        if self.is_int16xint8:
            if int16x8_int32bias:
                converter._experimental_full_integer_quantization_bias_type = tf.int32
            converter.target_spec.supported_ops = [
                tf.lite.OpsSet.EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8
            ]
        else:
            converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = inttype
        converter.inference_output_type = inttype
        tflite_model = converter.convert()

        os.makedirs(os.path.dirname(self.model_path_tflite), exist_ok=True)
        with open(self.model_path_tflite, "wb") as model:
            model.write(tflite_model)

    def interpret_model(self, input_data, inttype):
        interpreter = self.Interpreter(model_path=str(self.model_path_tflite),
                                       experimental_op_resolver_type=self.OpResolverType.BUILTIN_REF)
        interpreter.allocate_tensors()

        output_details = interpreter.get_output_details()
        (self.output_scale, self.output_zero_point) = output_details[0]['quantization']

        if input_data is not None:
            input_details = interpreter.get_input_details()
            (self.input_scale, self.input_zero_point) = input_details[0]['quantization']

            # Set input tensors
            interpreter.set_tensor(input_details[0]["index"], tf.cast(input_data, inttype))

        return interpreter

    def generate_json_from_template(self,
                                    weights_feature_data=None,
                                    weights_time_data=None,
                                    bias_data=None,
                                    int8_time_weights=False,
                                    bias_buffer=3):
        """
        Takes a json template and parameters as input and creates a new json file.
        """
        generated_json_file = self.model_path + '.json'

        with open(self.json_template, 'r') as in_file, open(generated_json_file, 'w') as out_file:
            # Update shapes, scales and zero points
            data = in_file.read()
            for item, to_replace in self.json_replacements.items():
                data = data.replace(item, str(to_replace))

            data = json.loads(data)

            # Update weights and bias data
            if weights_feature_data is not None:
                w_1_buffer_index = 1
                data["buffers"][w_1_buffer_index]["data"] = self.to_bytes(weights_feature_data.numpy().ravel(), 1)
            if weights_time_data is not None:
                w_2_buffer_index = 2
                if int8_time_weights:
                    data["buffers"][w_2_buffer_index]["data"] = self.to_bytes(weights_time_data.numpy().ravel(), 1)
                else:
                    data["buffers"][w_2_buffer_index]["data"] = self.to_bytes(weights_time_data.numpy().ravel(), 2)

            if bias_data is not None:
                bias_buffer_index = bias_buffer
                data["buffers"][bias_buffer_index]["data"] = self.to_bytes(bias_data.numpy().ravel(), 4)

            json.dump(data, out_file, indent=2)

        return generated_json_file

    def flatc_generate_tflite(self, json_input, schema):
        flatc = 'flatc'
        if schema is None:
            raise RuntimeError("A schema file is required.")
        command = "{} -o {} -c -b {} {}".format(flatc, self.headers_dir, schema, json_input)
        command_list = command.split(' ')
        try:
            process = subprocess.run(command_list)
            if process.returncode != 0:
                print(f"ERROR: {command = }")
                sys.exit(1)
        except Exception as e:
            raise RuntimeError(f"{e} from: {command = }. Did you install flatc?")

    def to_bytes(self, tensor_data, type_size) -> bytes:
        result_bytes = []

        if type_size == 1:
            tensor_type = np.uint8
        elif type_size == 2:
            tensor_type = np.uint16
        elif type_size == 4:
            tensor_type = np.uint32
        else:
            raise RuntimeError("Size not supported: {}".format(type_size))

        for val in tensor_data:
            for byte in int(tensor_type(val)).to_bytes(type_size, 'little'):
                result_bytes.append(byte)

        return result_bytes
