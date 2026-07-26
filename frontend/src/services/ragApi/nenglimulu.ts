// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Capabilities GET /api/v1/capabilities */
export async function capabilitiesList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.capabilitiesListParams,
  options?: { [key: string]: any }
) {
  return request<API.CapabilityOptionResponse[]>("/api/v1/capabilities", {
    method: "GET",
    params: {
      ...params,
    },
    ...(options || {}),
  });
}

/** Get Capability GET /api/v1/capabilities/${param0}/versions/${param1} */
export async function capabilitiesGetVersion(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.capabilitiesGetVersionParams,
  options?: { [key: string]: any }
) {
  const { code: param0, version: param1, ...queryParams } = params;
  return request<API.CapabilityOptionResponse>(
    `/api/v1/capabilities/${param0}/versions/${param1}`,
    {
      method: "GET",
      params: {
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}
