# Speech pipeline

## Purpose

This document defines the boundaries surrounding audio input and output.

## Input path

    Microphone
        ↓
    AudioSource
        ↓
    AudioFrame stream
        ↓
    VADProvider
        ↓
    AudioSegment
        ↓
    STTProvider
        ↓
    transcript text

## AudioSource

AudioSource owns microphone capture.

It produces small audio frames and must hide backend-specific objects from the
rest of Companion.

A consumer should never need to know whether capture uses sounddevice,
PortAudio, CoreAudio, PipeWire, or another implementation.

## AudioFrame

An AudioFrame represents a chunk of raw speech-pipeline audio.

Initial canonical audio should be:

- mono;
- signed 16-bit PCM;
- little endian;
- 16 kHz where practical.

The representation must include enough metadata to validate its sample rate
and channel count.

## VADProvider

VADProvider determines when a spoken utterance begins and ends.

The initial intended implementation is Silero VAD.

The core runtime must not import Silero.

VAD consumes AudioSource data and returns one AudioSegment representing a
complete user utterance.

## STTProvider

STTProvider converts an AudioSegment into text.

The initial intended implementation is faster-whisper.

The core runtime must not import faster-whisper.

## Output path

    assistant response text
            ↓
        TTSProvider
            ↓
        audio playback
            ↓
          Speaker

TTS implementation details are hidden behind TTSProvider.

## Barge-in

The architecture must allow microphone/VAD activity to interrupt assistant
speech.

Future behavior:

    SPEAKING
       │
       │ user begins speaking
       ▼
    cancel current TTS
       │
       ▼
    LISTENING

Provider interfaces must therefore avoid designs that make cancellation
impossible.
