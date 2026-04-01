# Training a Custom Piper TTS Voice

This project uses [Piper](https://github.com/OHF-Voice/piper1-gpl) as its TTS engine. Piper works great as a real-time(ish) TTS engine for Raspberry Pis. Other engines (Coqui, F5-TTS, Kokoro) offer better quality or style control, but aren't real time in this compute envelope. Training new voices for Piper is not hard, although there are many, many, steps required.

Literature claims about 1 hour of audio is needed to fine-tune an existing model (ie give it a new voice). Training from scratch is 10x that. The recordings need to be, of course, high quality, with no reverb, echo or noise, all from the same voice. For Piper, the training format is 22050 Hz S16 mono. If you want your new voice to sound in a specific way (eg angry), then make sure your training data is... angry.


## Training data

You will need to provide training data as individual files, plus a CSV that references the wav file + the text. Something like

```
wavs/001|This is the first sentence.
wavs/002|Here is another sentence.
```

Of course, it's unlikely you'll record (or find) an hour of audio in this format. Instead, and much more likely, you'll end up with a single long recording which then can be chopped up in more manageable pieces. For this,

1. `apt-get install ffmpeg`
1. `pip install -U openai-whisper [--break-system-packages]`
1. If needed, pre-preprocess your input (use Audacity to downmix to mono, cut unnecessarily long silences, etc)
1. Run the [prep dataset script](./prepare_dataset.py)
1. Run the [validate dataset script](./validate_dataset.py). This does the same as prepare, but on the small snippets. Quite a few will have bad alignment and throw off the training.

The script uses [Whisper](https://github.com/openai/whisper) to transcribe and get timestamps from the big wav file, and then chop it up into smaller ones. You should end up with two CSV files, one for "high confidence" sentences and one for the utterances where the model wasn't quite able to transcribe or find a clean sentence boundary.

[Tip: if you're getting your material from an online source, do `pw-record out.wav` and use qpwgraph as a patch bay to route to a wav file]


## Training

The training READMEs of both the [old, archived, Piper project](https://github.com/rhasspy/piper/blob/master/TRAINING.md), and the [new forked Piper project](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md) include training docs. I found I needed to read both to build this training guide.

We're not training from scratch, so pick a [checkpoint in HuggingFace](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main). If you'll train an English voice, pick an en model - the closest one you can find to your target voice.

Once you have your checkpoint and training data,

1. `sudo apt-get install python3-dev cmake build-essential python3-scikit-build-core`
1. `git clone https://github.com/OHF-voice/piper1-gpl.git`
1. Create a venv (we'll install a ton of Python packages): `cd piper1-gpl && python3 -m venv .venv`
1. `source .venv/bin/activate`
1. `python3 -m pip install -e '.[train]'`
1. `./build_monotonic_align.sh`
1. `pip install scikit-build-core`
1. `pip install scikit-build`
1. `pip install tensorboard` If you want to monitor progress (you do)
1. `python3 setup.py build_ext --inplace`

At this point, you should have an environment ready for training, which I trigger with

```
python3 -m piper.train fit \
  --data.voice_name "Nico" \
  --data.csv_path metadata.csv \
  --data.audio_dir $WAVs \
  --model.sample_rate 22050 \
  --data.espeak_voice "es-AR" \
  --data.cache_dir ./cache \
  --data.config_path '$COPY_OF_CHECKPOINTS_config.json' \
  --data.batch_size 22 \
  --data.num_workers 8 \
  --trainer.precision 16-mixed \
  --ckpt_path '$PATH_TO_CHECKPOINT'
```

I would be surprised if this works out of the box, however. A few things I needed to fiddle with to get this running:

1. Module names: some manuals say `python3 -m piper.train`, others say `python3 -m piper_train.fit`. You may need to read some code to find out which one you need.
1. Model mismatches; I downloaded a high quality checkpoint but was trying to train a mid quality model. This will error out with Torch complaining of architecture mismatches (I fixed by downloading a mid quality model)
1. Metadata CSV format may be wrong, it may or may not want the file extension in the CSV file
1. OOMs, of course. You'll need to play with batch_size and num_workers to fit your training system (You aren't training in your target, right?)
1. Piper refused to load the checkpoint due to Torch version differences. My LLM provided a [script to hack an existing checkpoint into something that Piper liked](./resave_ckpt.py).


## Finish Training

While training, you can run `tensorboard --logdir ./training/lightning_logs`, this will create a web UI with information on training progress, and a few audio samples you can listen to. You can stop training once the loss stops going down for a few epochs, or when the audio samples start sounding good enough. The manual claims there is a way to test with arbitrary sentences while training, however, I couldn't make it work.

For reference, in a system with an I7 10th gen + RT2080 (8GB) training was done in about 20 minutes, maybe less. In an old i7 6th gen and 16 GB RAM (no GPU) training would complete after the heat death of the universe.

Once done, you can export your model with `python3 -m piper_train.export_onnx /path/to/model.ckpt /path/to/model.onnx` and `cp /path/to/training_dir/config.json /path/to/model.onnx.json`


## Linklist

* [Checkpoints for fine-tuning in HuggingFace](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main)
* [Other person's notes on training Piper](https://advancedweb.hu/dataset-preparation-for-training-a-neural-text-to-speech-model-with-piper-tts/)
* [Old Piper training docs](https://github.com/rhasspy/piper/blob/master/TRAINING.md)
* [New Piper training docs](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md)

Alternative engines:

* [Kokoro](https://github.com/hexgrad/kokoro): better quality and style control, but not real time on a Pi
* [F5-TTS](https://github.com/SWivid/F5-TTS): better quality and style control, but not real time anywhere. Needs a GPU.

