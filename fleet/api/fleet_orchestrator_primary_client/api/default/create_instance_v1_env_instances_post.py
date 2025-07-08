from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.instance_request import InstanceRequest
from ...models.instance_response import InstanceResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: InstanceRequest,
    x_jwt_token: Union[None, Unset, str] = UNSET,
    x_team_id: Union[None, Unset, str] = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_jwt_token, Unset):
        headers["X-JWT-Token"] = x_jwt_token

    if not isinstance(x_team_id, Unset):
        headers["X-Team-ID"] = x_team_id

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/env/instances",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[HTTPValidationError, InstanceResponse]]:
    if response.status_code == 200:
        response_200 = InstanceResponse.from_dict(response.json())

        return response_200
    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[HTTPValidationError, InstanceResponse]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: InstanceRequest,
    x_jwt_token: Union[None, Unset, str] = UNSET,
    x_team_id: Union[None, Unset, str] = UNSET,
) -> Response[Union[HTTPValidationError, InstanceResponse]]:
    """Create Instance

    Args:
        x_jwt_token (Union[None, Unset, str]):
        x_team_id (Union[None, Unset, str]):
        body (InstanceRequest): Model for creating a new instance.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[HTTPValidationError, InstanceResponse]]
    """

    kwargs = _get_kwargs(
        body=body,
        x_jwt_token=x_jwt_token,
        x_team_id=x_team_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: InstanceRequest,
    x_jwt_token: Union[None, Unset, str] = UNSET,
    x_team_id: Union[None, Unset, str] = UNSET,
) -> Optional[Union[HTTPValidationError, InstanceResponse]]:
    """Create Instance

    Args:
        x_jwt_token (Union[None, Unset, str]):
        x_team_id (Union[None, Unset, str]):
        body (InstanceRequest): Model for creating a new instance.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[HTTPValidationError, InstanceResponse]
    """

    return sync_detailed(
        client=client,
        body=body,
        x_jwt_token=x_jwt_token,
        x_team_id=x_team_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: InstanceRequest,
    x_jwt_token: Union[None, Unset, str] = UNSET,
    x_team_id: Union[None, Unset, str] = UNSET,
) -> Response[Union[HTTPValidationError, InstanceResponse]]:
    """Create Instance

    Args:
        x_jwt_token (Union[None, Unset, str]):
        x_team_id (Union[None, Unset, str]):
        body (InstanceRequest): Model for creating a new instance.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[HTTPValidationError, InstanceResponse]]
    """

    kwargs = _get_kwargs(
        body=body,
        x_jwt_token=x_jwt_token,
        x_team_id=x_team_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: InstanceRequest,
    x_jwt_token: Union[None, Unset, str] = UNSET,
    x_team_id: Union[None, Unset, str] = UNSET,
) -> Optional[Union[HTTPValidationError, InstanceResponse]]:
    """Create Instance

    Args:
        x_jwt_token (Union[None, Unset, str]):
        x_team_id (Union[None, Unset, str]):
        body (InstanceRequest): Model for creating a new instance.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[HTTPValidationError, InstanceResponse]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_jwt_token=x_jwt_token,
            x_team_id=x_team_id,
        )
    ).parsed
