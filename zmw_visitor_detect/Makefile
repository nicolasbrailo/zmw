include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install opencv-python-headless

download_models:
	mkdir -p ./models
	cd ./models && \
		wget -nc 'https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel' && \
		wget -nc -O face_deploy.prototxt 'https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt' && \
		wget -nc 'https://storage.cmusatyalab.org/openface-models/nn4.small2.v1.t7' && \
		wget -nc 'https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx'


