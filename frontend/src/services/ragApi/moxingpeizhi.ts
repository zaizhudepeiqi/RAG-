// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Models GET /api/v1/models */
export async function modelsList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsListParams,
  options?: { [key: string]: any }
) {
  return request<API.ModelPageView>("/api/v1/models", {
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

/** Create Model POST /api/v1/models */
export async function modelsCreate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsCreateParams,
  body: API.CreateModelRequest,
  options?: { [key: string]: any }
) {
  return request<API.ModelView>("/api/v1/models", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}

/** Get Model GET /api/v1/models/${param0} */
export async function modelsGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsGetParams,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<API.ModelView>(`/api/v1/models/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Delete Model DELETE /api/v1/models/${param0} */
export async function modelsDelete(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsDeleteParams,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/models/${param0}`, {
    method: "DELETE",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}

/** Update Model PATCH /api/v1/models/${param0} */
export async function modelsUpdate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsUpdateParams,
  body: API.UpdateModelRequest,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<API.ModelView>(`/api/v1/models/${param0}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Model References GET /api/v1/models/${param0}/references */
export async function modelsReferences(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsReferencesParams,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<API.ModelReferenceView[]>(
    `/api/v1/models/${param0}/references`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Disable Model POST /api/v1/models/${param0}%3Adisable */
export async function modelsDisable(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsDisableParams,
  body: API.ModelStateRequest,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<API.ModelView>(`/api/v1/models/${param0}%3Adisable`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Enable Model POST /api/v1/models/${param0}%3Aenable */
export async function modelsEnable(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsEnableParams,
  body: API.ModelStateRequest,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<API.ModelView>(`/api/v1/models/${param0}%3Aenable`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Verify Model POST /api/v1/models/${param0}%3Averify */
export async function modelsVerify(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.modelsVerifyParams,
  body: API.ModelStateRequest,
  options?: { [key: string]: any }
) {
  const { modelId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/models/${param0}%3Averify`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}
