include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install opencv-python-headless onnxruntime openvino numpy

# GPU support: video decoding (VA-API, config hw_decode) needs Intel's VA driver; models on the GPU (OpenVINO) need
# Intel's compute runtime (OpenCL). Both need the service user in the group that owns the GPU device (usually
# "render"). The service only sees the new group once restarted. Check with make check_gpu.
GPU_DEVICE = /dev/dri/renderD128
setup_gpu:
	sudo apt-get install -y intel-media-va-driver-non-free vainfo intel-opencl-icd clinfo
	sudo usermod -aG "$$(stat -c %G $(GPU_DEVICE))" $(USER)
	@echo "Added $(USER) to group $$(stat -c %G $(GPU_DEVICE)). Restart the service (it only sees the group" \
		"after a restart), then check the Status page or run make check_gpu"

# Decoding: the VA driver, then the service's GPU self test (same ffmpeg command as HwDecoder). Compute: the GPU as
# an OpenCL device (what OpenVINO uses). Runs with the device's group even if this shell predates setup_gpu
# (through sudo; no sg on Ubuntu servers)
GPU_SELF_TEST = vainfo --display drm --device $(GPU_DEVICE) 2>&1 | grep -i -E 'driver|H264' && \
	ffmpeg -v error -nostdin -init_hw_device vaapi=va:$(GPU_DEVICE) -filter_hw_device va \
		-f lavfi -i testsrc=size=256x256:rate=1 -vf format=nv12,hwupload -frames:v 1 -f null - && \
	echo GPU decoding OK && \
	clinfo -l 2>&1 | grep -i -E 'platform|device' && clinfo -l 2>&1 | grep -q -i 'graphics' && \
	echo GPU compute OK
check_gpu:
	@grp="$$(stat -c %G $(GPU_DEVICE))"; \
	if id -nG | grep -qw "$$grp"; then sh -c "$(GPU_SELF_TEST)"; \
	else sudo -u $(USER) -g "$$grp" sh -c "$(GPU_SELF_TEST)"; fi

# Models chosen in ~/src/visitordetect (see its CLAUDE.md). wget -nc exits non-zero when the file exists
# (wget2), so every fetch is guarded with test -f.
download_models: export_yolo
	mkdir -p ./models
	cd ./models && \
		( test -f yolox_m.onnx || wget 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx' ) && \
		( test -f det_10g.onnx -a -f w600k_r50.onnx || \
			( wget -O buffalo_l.zip 'https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip' && \
			  unzip -o buffalo_l.zip det_10g.onnx w600k_r50.onnx && \
			  rm -f buffalo_l.zip ) )

# YOLO11m only ships as .pt: export it to ONNX in a throwaway venv, so torch never becomes a runtime dependency.
export_yolo:
	mkdir -p ./models
	test -f ./models/yolo11m.onnx || ( \
		python3 -m venv ./models/.export-venv && \
		./models/.export-venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu \
			--extra-index-url https://pypi.org/simple torch torchvision ultralytics onnx onnxslim && \
		mkdir -p ./models/.export && \
		cd ./models/.export && \
		../.export-venv/bin/yolo export model=yolo11m.pt format=onnx imgsz=640 opset=17 && \
		mv yolo11m.onnx .. && \
		cd .. && rm -rf .export .export-venv )

# End-to-end test of the running service: plays a known clip as the doorbell's live stream (expect a person, an
# unknown face and an identified one, once visitors exist). It's a real session: it feeds the identity store.
INJECT_CLIP = /home/batman/nvrish/doorbell/20261120_083830.mp4
test_inject_clip:
		mosquitto_pub -t 'zmw_visitor_detect/inject_clip' -m '{"cam_alias": "doorbell", "path": "$(INJECT_CLIP)"}'
test_inject_clip_reply:
	mosquitto_sub -t 'zmw_visitor_detect/inject_clip_reply'
