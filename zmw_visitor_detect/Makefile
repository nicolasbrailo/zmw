include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install opencv-python-headless

MOBILENET_BASE = https://raw.githubusercontent.com/djmv/MobilNet_SSD_opencv/master
FACE_DETECT_MODEL = https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830
FACE_DETECT_PROTO = https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector
OPENFACE_MODEL = https://storage.cmusatyalab.org/openface-models
YUNET_MODEL = https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet

download_models:
	mkdir -p ./models
	cd ./models && \
		wget -nc '$(MOBILENET_BASE)/MobileNetSSD_deploy.prototxt' && \
		wget -nc '$(MOBILENET_BASE)/MobileNetSSD_deploy.caffemodel' && \
		wget -nc '$(FACE_DETECT_MODEL)/res10_300x300_ssd_iter_140000.caffemodel' && \
		wget -nc -O face_deploy.prototxt '$(FACE_DETECT_PROTO)/deploy.prototxt' && \
		wget -nc '$(OPENFACE_MODEL)/nn4.small2.v1.t7' && \
		wget -nc '$(YUNET_MODEL)/face_detection_yunet_2023mar.onnx'


