# Blur Check AI quality model: license and provenance

`clipiqa_plus_rn50.onnx` is **CLIP-IQA+** (Wang, Chan & Loy, *Exploring CLIP for
Assessing the Look and Feel of Images*, AAAI 2023), as packaged by
[pyiqa](https://github.com/chaofengc/IQA-PyTorch), exported to ONNX by
`tools/export_quality_model.py`. It is not part of this repository's code and is
**not** covered by its MIT license.

It combines:

- **OpenAI CLIP ResNet-50 image encoder**: MIT License, Copyright (c) 2021 OpenAI
  (https://github.com/openai/CLIP).
- **Two learned prompt embeddings** ("good photo" / "bad photo") trained on the
  KonIQ-10k dataset, from pyiqa, under the **PolyForm Noncommercial License 1.0.0**
  (https://polyformproject.org/licenses/noncommercial/1.0.0/).

Because of the second component, the model file may be used and redistributed
**for non-commercial purposes only**.

SHA-256: `96693a1f8d1d1c00c64e8be95420f6772238e73dea0df009951ab6aaf1f9dc9d`
