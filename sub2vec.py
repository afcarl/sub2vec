# -*- coding: utf-8 -*-
# jvparidon@gmail.com
import os
import argparse
import numpy as np
import subprocess as sp
import strip_subs
import join_subs
import deduplicate
from utensilities import timer
from multiprocessing import cpu_count
import logging
logging.basicConfig(format='[{levelname}] {message}', style='{', level=logging.INFO)


@timer
def train_fasttext(training_data, cores, d=300, neg=10, epoch=10, t=.0001):
    binary = ['fasttext']
    method = ['skipgram']
    train = ['-input', training_data]
    #model_name = training_data.replace('.txt', '.neg{}.epoch{}.t{}.{}d'.format(neg, epoch, t, d))
    model_name = 'sub.{}'.format(training_data.split('.')[0])
    output = ['-output', model_name]
    neg = ['-neg', str(neg)]
    epoch = ['-epoch', str(epoch)]
    t = ['-t', str(t)]
    dim = ['-dim', str(d)]
    thread = ['-thread', str(cores)]
    if logging.getLogger().isEnabledFor(logging.INFO):
        sp.run(binary + method + train + output + neg + epoch + t + dim + thread)
    else:
        sp.run(binary + method + train + output + neg + epoch + t + dim + thread, stdout=sp.DEVNULL)
    model = '{}.bin'.format(model_name)
    vecs = '{}.vec'.format(model_name)
    return model, vecs


@timer
def build_phrases(training_data, phrase_pass):
    base_fname = training_data.replace('.txt', '')
    for i in range(phrase_pass):
        t = (2 ** (phrase_pass - i - 1)) * 100
        binary = ['word2phrase']
        train = ['-train', training_data]
        out_fname = '{}.{}pass.d5.t{}.txt'.format(base_fname, i + 1, t)
        output = ['-output', out_fname]
        d = ['-min-count', str(5)]
        t = ['-threshold', str(t)]
        if logging.getLogger().isEnabledFor(logging.INFO):
            sp.run(binary + train + output + d + t)
        else:
            sp.run(binary + train + output + d + t, stdout=sp.DEVNULL)
        training_data = out_fname
    return out_fname


def fix_encoding(training_data):
    out_fname = training_data.replace('.txt', '.utf-8.txt')
    with open(training_data, 'r', encoding='utf-8', errors='ignore') as in_file, open(out_fname, 'w', encoding='utf-8') as out_file:
        for line in in_file:
            out_file.write(line)
    return out_fname


@timer
def generate(lang, subs_dir, no_subs_prep, no_dedup, phrase_pass, cores, subset_years=(0, 2020)):
    if lang == 'all':
        langs = reversed(sorted(os.listdir(os.path.join(subs_dir, 'raw'))))
    else:
        langs = [lang]
    for lang in langs:
        # prep subs
        if no_subs_prep:
            logging.info('skipping subtitle xml-stripping and file concatenation')
        else:
            training_data = os.path.join(subs_dir, 'raw')
            # strip subs
            logging.info('stripping xml from subs in language {}'.format(lang))
            results, t = strip_subs.strip_parallelized(training_data, lang, ioformat='txt', cores=cores)
            logging.info('stripped xml from {} files in {} seconds'.format(np.sum(results), int(t['duration'])))
            # join subs
            logging.info('concatenating training data for language {}'.format(lang))
            results, t = join_subs.join_dir(training_data, './', lang, verbose=True, ioformat='txt', subset_years=subset_years)
            logging.info('concatenated {} files in {} seconds'.format(results, int(t['duration'])))

        training_data = '{}.{}-{}.txt'.format(lang, *subset_years)

        # deduplicate
        if no_dedup:
            logging.info('skipping subtitle xml-stripping and file concatenation')
        else:
            logging.info('deduplicating {}'.format(training_data))
            out_fname = training_data.replace('.txt', '.dedup.txt')
            results, t = deduplicate.dedup_file(training_data, out_fname)
            n_lines, n_duplicates = results
            training_data = out_fname
            logging.info('read {} lines and removed {} duplicates in {} seconds'.format(n_lines, n_duplicates,
                                                                                 int(t['duration'])))

        # build phrases
        logging.info('building phrases for {}'.format(training_data))
        training_data, t = build_phrases(training_data, phrase_pass)
        logging.info('built phrases in {} passes in {} seconds'.format(phrase_pass, int(t['duration'])))

        # fix potential broken utf-8 encoding
        logging.info('checking (and fixing) utf-8 encoding for {}'.format(training_data))
        training_data = fix_encoding(training_data)

        # train fastText model
        logging.info('training fastText model on {}'.format(training_data))
        results, t = train_fasttext(training_data, cores)
        model, vecs = results
        logging.info('trained fastText model in {} seconds'.format(int(t['duration'])))
        logging.info('model binary at {}'.format(model))
        logging.info('word vectors at {}'.format(vecs))

    return langs


if __name__ == '__main__':
    argparser = argparse.ArgumentParser(description='generate a fastText model from OpenSubtitles data')
    argparser.add_argument('--lang', default='en',
                           help='source language (OpenSubtitles data uses ISO 639-1 codes, use "all" for all languages)')
    argparser.add_argument('--subs_dir', default='../OpenSubtitles2018',
                           help='location of OpenSubtitles data')
    argparser.add_argument('--no_subs_prep', action='store_true',
                           help='do not xml-strip and concatenate subs')
    argparser.add_argument('--no_dedup', action='store_true',
                           help='do not deduplicate training data line-wise')
    argparser.add_argument('--phrase_pass', default='5', type=int,
                           help='number of phrase-building passes, 0 equals no phrase-building (default 5)')
    argparser.add_argument('--cores', default=int(cpu_count() / 2), type=int,
                           help='number of cores to use for the parts that can be parallelized')
    args = argparser.parse_args()

    langs, t = generate(**vars(args))
    for lang in langs:
        logging.info('generated sub2vec model for language {} in {} seconds'.format(lang, int(t['duration'])))
