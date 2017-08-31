#
"""
Various database classes that define data reading, parsing, batching, and other
preprocessing operations.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import copy

import tensorflow as tf
import tensorflow.contrib.slim as tf_slim

from txtgen.hyperparams import HParams
from txtgen.core import utils
from txtgen.data.text_data_decoder import TextDataDecoder
from txtgen.data.vocabulary import Vocab
from txtgen.data.embedding import Embedding


def default_text_dataset_hparams():
    """Returns a dictionary of hyperparameters of a text dataset with default
    values.
    """
    return {
        "name": "",
        "files": "",
        "vocab.file": "",
        "vocab.share_with": "",
        "embedding": {
            "file": "",
            "read_fn": "load_word2vec",
            "share_with": ""
        },
        "reader": {
            "type": "tensorflow.TextLineReader",
            "kwargs": {}
        },
        "processing": {
            "split_level": "word",
            "delimiter": " ",
            "max_seq_length": None,
            "bos_token": "<BOS>",
            "eos_token": "<EOS>"
        }
    }

class DataBaseBase(object):
    """Base class of all data classes.
    """

    def __init__(self, hparams, name="database"):
        self.name = name
        self._hparams = HParams(hparams, self.default_hparams())

    @staticmethod
    def default_hparams():
        """Returns a dicitionary of default hyperparameters.
        """
        return {
            "num_epochs": 1,
            "batch_size": 64,
            "allow_smaller_final_batch": False,
            "bucket_boundaries": None,
            "shuffle": True,
            "seed": None
        }

    @staticmethod
    def make_dataset(dataset_hparams):
        """Creates a Dataset instance that defines source filenames, data
        reading, and decoding.
        """
        raise NotImplementedError

    def _make_data_provider(self, dataset):
        """Creates a DataProvider instance that provides a single example of
        requested data.

        Args:
            dataset: An instance of the Dataset class.
        """
        raise NotImplementedError

    def __call__(self):
        """Returns a batch of data.
        """
        raise NotImplementedError


class TextDataBase(DataBaseBase):
    """Text data class that reads text files.
    """

    def __init__(self, hparams, name="text_database"):
        DataBaseBase.__init__(self, hparams, name)
        self._dataset = self.make_dataset(self._hparams.dataset)
        self._data_provider = self._make_data_provider(self._dataset)

    @staticmethod
    def default_hparams():
        """Returns a dicitionary of default hyperparameters.
        """
        hparams = copy.deepcopy(DataBaseBase.default_hparams())
        hparams.update({
            "dataset": default_text_dataset_hparams()
        })
        return hparams

    @staticmethod
    def make_dataset(dataset_hparams):
        proc_hparams = dataset_hparams["processing"]

        # Load vocabulary
        bos_token = utils.default_string(proc_hparams["bos_token"], "<BOS>")
        eos_token = utils.default_string(proc_hparams["eos_token"], "<EOS>")
        vocab = Vocab(dataset_hparams["vocab.file"],
                      bos_token=bos_token,
                      eos_token=eos_token)

        # Get the reader class
        reader_class = utils.get_class(dataset_hparams["reader"]["type"],
                                       ["tensorflow"])

        # Create data decoder
        decoder = TextDataDecoder(
            split_level=proc_hparams["split_level"],
            delimiter=proc_hparams["delimiter"],
            bos_token=proc_hparams["bos_token"],
            eos_token=proc_hparams["eos_token"],
            max_seq_length=proc_hparams["max_seq_length"],
            token_to_id_map=vocab.token_to_id_map)


        # Load embedding (optional)
        emb_hparams = dataset_hparams["embedding"]
        embedding = None
        if emb_hparams["file"] is not None and len(emb_hparams["file"]) > 0:
            emb_read_fn = utils.get_function(
                emb_hparams["read_fn"],
                ["txtgen.custom", "txtgen.data.embedding"])
            embedding = Embedding(emb_hparams["file"],
                                  vocab.token_to_id_map_py,
                                  emb_read_fn)

        # Create the dataset
        dataset = tf_slim.dataset.Dataset(
            data_sources=dataset_hparams["files"],
            reader=reader_class,
            decoder=decoder,
            num_samples=None,
            items_to_descriptions=None,
            vocab=vocab,
            embedding=embedding,
            name=dataset_hparams["name"])

        return dataset

    def _make_data_provider(self, dataset):
        data_provider = tf_slim.dataset_data_provider.DatasetDataProvider(
            dataset=dataset,
            num_readers=1, #TODO(zhiting): allow more readers
            reader_kwargs=self._hparams.dataset["reader"]["kwargs"],
            shuffle=self._hparams.shuffle,
            num_epochs=self._hparams.num_epochs,
            common_queue_capacity=1024,
            common_queue_min=526,
            seed=self._hparams.seed)
        return data_provider

    def __call__(self):
        data = self._data_provider.get(self._data_provider.list_items())
        data = dict(zip(self._data_provider.list_items(), data))

        if self._hparams.bucket_boundaries is None:
            data_batch = tf.train.batch(
                tensors=data,
                batch_size=self._hparams.batch_size,
                num_threads=1,
                capacity=32*self._hparams.batch_size+1024,
                enqueue_many=False,
                dynamic_pad=True,
                allow_smaller_final_batch=self._hparams.allow_smaller_final_batch,
                name="text_data_batch")
        else:
            input_length = data[self._dataset.decoder.length_tensor_name] # pylint: disable=no-member
            _, data_batch = tf.contrib.training.bucket_by_sequence_length(
                input_length=input_length,
                tensors=data,
                batch_size=self._hparams.batch_size,
                bucket_boundaries=self._hparams.bucket_boundaries,
                num_threads=1,
                capacity=32*self._hparams.batch_size+1024,
                dynamic_pad=True,
                allow_smaller_final_batch=self._hparams.allow_smaller_final_batch,
                keep_input=input_length > 0,
                name="text_data_bucket_batch")

        return data_batch








