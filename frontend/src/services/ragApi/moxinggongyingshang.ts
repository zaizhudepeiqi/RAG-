// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Model Providers GET /api/v1/model-providers */
export async function modelProvidersList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersListParams,
  options?: { [key: string]: any }
) {
  return request<API.ModelProviderPageView>("/api/v1/model-providers", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // pageSize has a default value: 20
      pageSize: "20",
      // sort has a default value: display_name
      sort: "display_name",
      ...params,
    },
    ...(options || {}),
  });
}

/** Create Model Provider POST /api/v1/model-providers */
export async function modelProvidersCreate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersCreateParams,
  body: API.CreateModelProviderRequest,
  options?: { [key: string]: any }
) {
  return request<API.ModelProviderView>("/api/v1/model-providers", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}

/** Get Model Provider GET /api/v1/model-providers/${param0} */
export async function modelProvidersGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersGetParams,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<API.ModelProviderView>(`/api/v1/model-providers/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Delete Model Provider DELETE /api/v1/model-providers/${param0} */
export async function modelProvidersDelete(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersDeleteParams,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/model-providers/${param0}`, {
    method: "DELETE",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}

/** Update Model Provider PATCH /api/v1/model-providers/${param0} */
export async function modelProvidersUpdate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersUpdateParams,
  body: API.UpdateModelProviderRequest,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<API.ModelProviderView>(`/api/v1/model-providers/${param0}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** List Discovered Models GET /api/v1/model-providers/${param0}/discovered-models */
export async function modelProvidersDiscoveredModelsList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersDiscoveredModelsListParams,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<API.DiscoveredModelView[]>(
    `/api/v1/model-providers/${param0}/discovered-models`,
    {
      method: "GET",
      params: {
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** Discover Provider Models POST /api/v1/model-providers/${param0}%3Adiscover-models */
export async function modelProvidersDiscover(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersDiscoverParams,
  body: API.ProviderOperationRequest,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/model-providers/${param0}%3Adiscover-models`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Test Model Provider POST /api/v1/model-providers/${param0}%3Atest */
export async function modelProvidersTest(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelProvidersTestParams,
  body: API.ProviderOperationRequest,
  options?: { [key: string]: any }
) {
  const { providerId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/model-providers/${param0}%3Atest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}
