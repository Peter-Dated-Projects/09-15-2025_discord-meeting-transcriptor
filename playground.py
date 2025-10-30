from pywhispercpp.model import Model

m = Model("assets/models/ggml-large-v2.bin", gpu=True)

target_file = r"C:\Users\peter\Videos\audio-recording-1.m4a"
transcription = m.transcribe(target_file)

print(transcription.text)
