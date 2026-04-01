include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install opencv-python-headless onnxruntime

download_models:
	mkdir -p ./models
	cd ./models && \
		wget -nc 'https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx' && \
		wget -nc 'https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx' && \
		( test -f w600k_r50.onnx || \
			( wget -nc -O buffalo_l.zip 'https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip' && \
			  unzip -o buffalo_l.zip w600k_r50.onnx && \
			  rm -f buffalo_l.zip ) )


