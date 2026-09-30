from setuptools import find_packages, setup

package_name = 'rescue_turtle'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch',
            ['launch/rescue_turtle.launch.py']),
    ],
    package_data={'': ['py.typed']},
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Jamie',
    maintainer_email='jamie-gastrich@users.noreply.github.com',
    description='Rescue one turtlesim turtle with another: spawner and rescue manager.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'spawner = rescue_turtle.spawner:main',
            'rescue_manager = rescue_turtle.rescue_manager:main',
        ],
    },
)
