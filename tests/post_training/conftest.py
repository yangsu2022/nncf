"""
 Copyright (c) 2023 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

import pytest
import numpy as np
from typing import Dict
from abc import abstractclassmethod
from pathlib import Path
from enum import Enum
from dataclasses import dataclass


def pytest_addoption(parser):
    parser.addoption("--data", action="store")
    parser.addoption("--output", action="store", default="./tmp/")
    parser.addoption("--backends", action="store", default="TORCH,TORCH_PTQ,ONNX,OV_NATIVE,OV")


def pytest_configure(config):
    config.test_results = {}


class PipelineType(Enum):
    FP32 = 'FP32'
    TORCH = 'Torch INT8'
    TORCH_PTQ = 'Torch PTQ INT8'
    ONNX = 'ONNX INT8'
    OV_NATIVE = 'OV Native INT8'
    OV = 'Openvino INT8'


@dataclass
class RunInfo:
    top_1: float
    FPS: float
    status: str = None


class TableColumn:
    @classmethod
    @abstractclassmethod
    def name(cls) -> str:
        """
        Name of the column.

        :returns: Name of the column.
        """

    @classmethod
    @abstractclassmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        """
        Is statistic applicable for given pipeline type.

        :param pipeline_type: Given pipeline type.
        :returns: Eather given pipeline type applicable or not.
        """

    @classmethod
    @abstractclassmethod
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        """
        Metod describes how to retrieve column info out of RunInfo.

        :param info: Runinfo to retrive column info.
        :param target_pipeline_type: Target type of the pipeline.
        :returns: Column info.
        """

    @staticmethod
    def assign_default_value(func):
        def wrapped_get_value(cls, info: Dict[PipelineType, RunInfo],
                              target_pipeline_type: PipelineType):
            if target_pipeline_type not in info:
                return '-'
            return func(cls, info, target_pipeline_type)
        return wrapped_get_value


class Top1Column(TableColumn):
    @classmethod
    def name(cls):
        return 'top 1'

    @classmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        return True

    @classmethod
    @TableColumn.assign_default_value
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        return info[target_pipeline_type].top_1


class FPSColumn(TableColumn):
    @classmethod
    def name(cls):
        return 'FPS'

    @classmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        return True

    @classmethod
    @TableColumn.assign_default_value
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        return info[target_pipeline_type].FPS


class Top1DiffColumn(TableColumn):
    @classmethod
    def name(cls):
        return 'top 1 diff'

    @classmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        return pipeline_type != PipelineType.FP32

    @classmethod
    @TableColumn.assign_default_value
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        return info[PipelineType.FP32].top_1 - info[target_pipeline_type].top_1


class FPSSpeedupColumn(TableColumn):
    @classmethod
    def name(cls):
        return 'FPS speedup'

    @classmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        return pipeline_type != PipelineType.FP32

    @classmethod
    @TableColumn.assign_default_value
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        if info[PipelineType.FP32].FPS > 1e-5:
            return info[target_pipeline_type].FPS / info[PipelineType.FP32].FPS
        return 'inf'


class StatusColumn(TableColumn):
    @classmethod
    def name(cls):
        return 'Status'

    @classmethod
    def accept_pipeline_type(cls, pipeline_type: PipelineType) -> bool:
        return True

    @classmethod
    def get_value(cls, info: Dict[PipelineType, RunInfo],
                  target_pipeline_type: PipelineType) -> str:
        status = []
        for pipeline_type in PipelineType:
            if pipeline_type in info:
                stat = info[pipeline_type].status
                if stat is not None:
                    status.append(stat)

        return ','.join(status)


@pytest.fixture
def backends_list(request):
    return request.config.getoption('--backends')


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    result = outcome.get_result()

    if result.when == 'call':
        test_results = item.config.test_results
        per_model_columns = [Top1Column, FPSColumn, Top1DiffColumn, FPSSpeedupColumn]
        grouped_columns = [StatusColumn]
        header = ["Model name"]
        for column in per_model_columns:
            for pipeline_type in PipelineType:
                if column.accept_pipeline_type(pipeline_type):
                    header.append(" ".join((pipeline_type.value, column.name())))
        for column in grouped_columns:
            header.append(column.name())

        table = []
        for model_name, run_infos in test_results.items():
            row = [model_name]
            for column in per_model_columns:
                for pipeline_type in PipelineType:
                    if column.accept_pipeline_type(pipeline_type):
                        row.append(column.get_value(run_infos, pipeline_type))
            table.append(row)
            for column in grouped_columns:
                row.append(column.get_value(run_infos, None))

        output_folder = Path(item.config.getoption("--output"))
        output_folder.mkdir(parents=True, exist_ok=True)
        np.savetxt(output_folder / "results.csv", table, delimiter=",", fmt='%s', header=','.join(header))
