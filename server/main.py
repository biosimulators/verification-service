import logging
import os
import tempfile
from typing import *

import uvicorn
import traceback
from pydantic import Field
from fastapi import FastAPI, UploadFile, File, Query, APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse

from server.handlers.compare import (
    generate_biosimulators_utc_species_comparison,
    generate_utc_comparison,
    generate_biosimulators_utc_comparison)
from server.handlers.io import save_uploaded_file, read_report_outputs
from server.data_model import ArchiveUploadResponse, UtcSpeciesComparison, UtcComparison, CustomError, SimulationError
from server.log_config import setup_logging


setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title='verification-service', version='1.0.0')
router = APIRouter()

origins = [
    'http://127.0.0.1:4200',
    'http://127.0.0.1:4201',
    'http://127.0.0.1:4202',
    'http://localhost:4200',
    'http://localhost:4201',
    'http://localhost:4202',
    'https://biosimulators.org',
    'https://www.biosimulators.org',
    'https://biosimulators.dev',
    'https://www.biosimulators.dev',
    'https://run.biosimulations.dev',
    'https://run.biosimulations.org',
    'https://biosimulations.dev',
    'https://biosimulations.org',
    'https://bio.libretexts.org',
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def universal_exception_handler(request: Request, exc: Exception):
    print(traceback.format_exc())  # This prints the full stack trace
    error_message = str(exc) if hasattr(exc, 'message') else "An unexpected error occurred"

    return JSONResponse(
        status_code=500,
        content=CustomError(detail=error_message).dict()
    )


@app.get("/")
def root():
    return {'verification-service-message': 'Hello from the Verification Service API!'}


# @app.post(
#     "/utc-comparison",
#     response_model=UtcComparison,
#     name="Uniform Time Course Comparison.",
#     operation_id="utc-comparison",
#     summary="Compare UTC outputs for each species in a given model file. You may pass either a model file or OMEX archive file.")
# async def utc_comparison(
#         uploaded_file: UploadFile = File(...),
#         simulators: List[str] = Query(default=['amici', 'copasi', 'tellurium']),
#         include_outputs: bool = Query(default=True),
#         comparison_id: str = Query(default=None),
#         # ground_truth: List[List[float]] = None,
#         # time_course_config: Dict[str, Union[int, float]] = Body(default=None)
# ) -> UtcComparison:
#     out_dir = tempfile.mkdtemp()
#     save_dir = tempfile.mkdtemp()
#     omex_path = await save_uploaded_file(uploaded_file, save_dir)
#     comparison_name = comparison_id or f'api-generated-utc-comparison-for-{simulators}'
#     # generate async comparison
#     comparison = generate_utc_comparison(
#         omex_fp=omex_path,
#         simulators=simulators,
#         include_outputs=include_outputs,
#         comparison_id=comparison_name)
#     spec_comparisons = []
#     for spec_name, comparison_data in comparison['results'].items():
#         species_comparison = UtcSpeciesComparison(
#             mse=comparison_data['mse'],
#             proximity=comparison_data['prox'],
#             output_data=comparison_data.get('output_data'),
#             species_name=spec_name)
#         spec_comparisons.append(species_comparison)
#     return UtcComparison(results=spec_comparisons, id=comparison_name, simulators=simulators)


@app.post(
    "/utc-comparison",  # "/biosimulators-utc-comparison",
    response_model=UtcComparison,
    name="Biosimulator Uniform Time Course Comparison",
    operation_id="biosimulators-utc-comparison",
    summary="Compare UTC outputs from Biosimulators for a model from a given archive.")
async def utc_comparison(
        uploaded_file: UploadFile = File(..., description="OMEX/COMBINE Archive File."),
        simulators: List[str] = Query(
            default=['amici', 'copasi', 'tellurium'],
            description="Simulators to include in the comparison."
        ),
        include_outputs: bool = Query(
            default=True,
            description="Whether to include the output data on which the comparison is based."
        ),
        comparison_id: str = Query(
            default=None,
            description="Descriptive identifier for this comparison."
        ),
        ground_truth_report: UploadFile = File(
            default=None,
            description="reports.h5 file defining the so-called ground-truth to be included in the comparison.")
        ) -> UtcComparison:

    try:
        save_dir = tempfile.mkdtemp()
        out_dir = tempfile.mkdtemp()
        omex_path = await save_uploaded_file(uploaded_file, save_dir)

        if ground_truth_report is not None:
            report_filepath = await save_uploaded_file(ground_truth_report, save_dir)
            ground_truth = await read_report_outputs(report_filepath)
            truth_vals = ground_truth.to_dict()['data']
            # d = [d.to_dict() for d in ground_truth.data if "time" not in d.dataset_label.lower()]
            # truth_vals = [data['data'].tolist() for data in d]
        else:
            truth_vals = None

        comparison_id = comparison_id or 'biosimulators-utc-comparison'
        comparison = await generate_biosimulators_utc_comparison(
            omex_fp=omex_path,
            out_dir=out_dir,  # TODO: replace this with an s3 endpoint.
            simulators=simulators,
            comparison_id=comparison_id,
            ground_truth=truth_vals)

        spec_comparisons = []
        for spec_name, comparison_data in comparison['results'].items():
            species_comparison = UtcSpeciesComparison(
                mse=comparison_data['mse'],
                proximity=comparison_data['prox'],
                output_data=comparison_data.get('output_data') if include_outputs else {},
                species_name=spec_name)
            spec_comparisons.append(species_comparison)
    except SimulationError as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return UtcComparison(
        results=spec_comparisons,
        id=comparison_id,
        simulators=simulators)


# @app.post(
#     "/biosimulators-utc-species-comparison",
#     response_model=UtcSpeciesComparison,
#     summary="Compare UTC outputs from Biosimulators for a given species name")
# async def biosimulators_utc_species_comparison(
#         uploaded_file: UploadFile = File(...),
#         species_id: str = Query(...),
#         simulators: List[str] = Query(default=['amici', 'copasi', 'tellurium']),
#         include_outputs: bool = Query(default=True)
# ) -> UtcSpeciesComparison:
#     # handle os structures
#     save_dir = tempfile.mkdtemp()
#     out_dir = tempfile.mkdtemp()
#     omex_path = os.path.join(save_dir, uploaded_file.filename)
#     with open(omex_path, 'wb') as file:
#         contents = await uploaded_file.read()
#         file.write(contents)
#     # generate async comparison
#     comparison = await generate_biosimulators_utc_species_comparison(
#         omex_fp=omex_path,
#         out_dir=out_dir,  # TODO: replace this with an s3 endpoint.
#         species_name=species_id,
#         simulators=simulators)
#     out_data = comparison['output_data'] if include_outputs else None
#     return UtcSpeciesComparison(
#         mse=comparison['mse'],
#         proximity=comparison['prox'],
#         output_data=out_data,
#         species_name=species_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
