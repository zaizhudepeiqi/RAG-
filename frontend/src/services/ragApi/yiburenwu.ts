// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Operations GET /api/v1/operations */
export async function operationsList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.operationsListParams,
  options?: { [key: string]: any }
) {
  return request<API.OperationPage>("/api/v1/operations", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // pageSize has a default value: 20
      pageSize: "20",
      // sort has a default value: -queued_at
      sort: "-queued_at",
      ...params,
    },
    ...(options || {}),
  });
}

/** Get Operation GET /api/v1/operations/${param0} */
export async function operationsGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.operationsGetParams,
  options?: { [key: string]: any }
) {
  const { operationId: param0, ...queryParams } = params;
  return request<API.OperationDetail>(`/api/v1/operations/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Cancel Operation POST /api/v1/operations/${param0}%3Acancel */
export async function operationsCancel(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.operationsCancelParams,
  options?: { [key: string]: any }
) {
  const { operationId: param0, ...queryParams } = params;
  return request<API.OperationDetail>(`/api/v1/operations/${param0}%3Acancel`, {
    method: "POST",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Retry Operation POST /api/v1/operations/${param0}%3Aretry */
export async function operationsRetry(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.operationsRetryParams,
  options?: { [key: string]: any }
) {
  const { operationId: param0, ...queryParams } = params;
  return request<API.OperationDetail>(`/api/v1/operations/${param0}%3Aretry`, {
    method: "POST",
    params: { ...queryParams },
    ...(options || {}),
  });
}
