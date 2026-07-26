// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Knowledge Bases GET /api/v1/knowledge-bases */
export async function knowledgeBasesList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesListParams,
  options?: { [key: string]: any }
) {
  return request<API.KnowledgeBasePageView>("/api/v1/knowledge-bases", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // pageSize has a default value: 20
      pageSize: "20",
      ...params,
    },
    ...(options || {}),
  });
}

/** Create Knowledge Base POST /api/v1/knowledge-bases */
export async function knowledgeBasesCreate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesCreateParams,
  body: API.CreateKnowledgeBaseRequest,
  options?: { [key: string]: any }
) {
  return request<API.CreateKnowledgeBaseResponse>("/api/v1/knowledge-bases", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}

/** Get Knowledge Base GET /api/v1/knowledge-bases/${param0} */
export async function knowledgeBasesGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesGetParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.KnowledgeBaseDetailView>(
    `/api/v1/knowledge-bases/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Delete Knowledge Base DELETE /api/v1/knowledge-bases/${param0} */
export async function knowledgeBasesDelete(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesDeleteParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/knowledge-bases/${param0}`, {
    method: "DELETE",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}

/** Update Knowledge Base Metadata PATCH /api/v1/knowledge-bases/${param0}/metadata */
export async function knowledgeBasesUpdateMetadata(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesUpdateMetadataParams,
  body: API.UpdateKnowledgeBaseMetadataRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.KnowledgeBaseDetailView>(
    `/api/v1/knowledge-bases/${param0}/metadata`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** Disable Knowledge Base POST /api/v1/knowledge-bases/${param0}%3Adisable */
export async function knowledgeBasesDisable(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesDisableParams,
  body: API.KnowledgeBaseStateRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.KnowledgeBaseDetailView>(
    `/api/v1/knowledge-bases/${param0}%3Adisable`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** Enable Knowledge Base POST /api/v1/knowledge-bases/${param0}%3Aenable */
export async function knowledgeBasesEnable(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesEnableParams,
  body: API.KnowledgeBaseStateRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.KnowledgeBaseDetailView>(
    `/api/v1/knowledge-bases/${param0}%3Aenable`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}
