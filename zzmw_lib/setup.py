from setuptools import setup, find_packages

setup(
    name="zzmw_lib",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "apscheduler>=3.10.4",
        "flask",
        "inotify-simple",
        "paho-mqtt",
        "systemd-python",
    ],
    extras_require={
        "geo": ["astral"],
        "z2m": [],
    },
)


