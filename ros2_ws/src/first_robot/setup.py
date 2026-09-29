from setuptools import find_packages, setup

package_name = 'first_robot'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    package_data={'': ['py.typed']},
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jamie',
    maintainer_email='jamie@todo.todo',
    description='First steps package: a minimal rclpy node that logs on a timer.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'first_robot_node = first_robot.first_robot_node:main',
        ],
    },
)
