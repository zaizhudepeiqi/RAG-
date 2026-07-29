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

/** Get Build Config GET /api/v1/knowledge-bases/${param0}/build-config */
export async function knowledgeBasesGetBuildConfig(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesGetBuildConfigParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.BuildConfigView>(
    `/api/v1/knowledge-bases/${param0}/build-config`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** List Generations GET /api/v1/knowledge-bases/${param0}/generations */
export async function knowledgeBasesListGenerations(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesListGenerationsParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.GenerationPageView>(
    `/api/v1/knowledge-bases/${param0}/generations`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Create Generation POST /api/v1/knowledge-bases/${param0}/generations */
export async function knowledgeBasesCreateGeneration(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesCreateGenerationParams,
  body: API.CreateGenerationRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/knowledge-bases/${param0}/generations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Get Generation GET /api/v1/knowledge-bases/${param0}/generations/${param1} */
export async function knowledgeBasesGetGeneration(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesGetGenerationParams,
  options?: { [key: string]: any }
) {
  const {
    knowledgeBaseId: param0,
    generationId: param1,
    ...queryParams
  } = params;
  return request<API.GenerationDetailView>(
    `/api/v1/knowledge-bases/${param0}/generations/${param1}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Discard Generation POST /api/v1/knowledge-bases/${param0}/generations/${param1}%3Adiscard */
export async function knowledgeBasesDiscardGeneration(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesDiscardGenerationParams,
  body: API.KnowledgeBaseStateRequest,
  options?: { [key: string]: any }
) {
  const {
    knowledgeBaseId: param0,
    generationId: param1,
    ...queryParams
  } = params;
  return request<API.GenerationSummaryView>(
    `/api/v1/knowledge-bases/${param0}/generations/${param1}%3Adiscard`,
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

/** Retry Generation Failed Items POST /api/v1/knowledge-bases/${param0}/generations/${param1}%3Aretry-failed */
export async function knowledgeBasesRetryGenerationFailedItems(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesRetryGenerationFailedItemsParams,
  options?: { [key: string]: any }
) {
  const {
    knowledgeBaseId: param0,
    generationId: param1,
    ...queryParams
  } = params;
  return request<any>(
    `/api/v1/knowledge-bases/${param0}/generations/${param1}%3Aretry-failed`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
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

/** Save Pending Build Config PUT /api/v1/knowledge-bases/${param0}/pending-build-config */
export async function knowledgeBasesSavePendingBuildConfig(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesSavePendingBuildConfigParams,
  body: API.UpdatePendingBuildConfigRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.BuildConfigView>(
    `/api/v1/knowledge-bases/${param0}/pending-build-config`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** Discard Pending Build Config DELETE /api/v1/knowledge-bases/${param0}/pending-build-config */
export async function knowledgeBasesDiscardPendingBuildConfig(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesDiscardPendingBuildConfigParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<any>(
    `/api/v1/knowledge-bases/${param0}/pending-build-config`,
    {
      method: "DELETE",
      params: {
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** Get Retrieval Config GET /api/v1/knowledge-bases/${param0}/retrieval-config */
export async function knowledgeBasesGetRetrievalConfig(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesGetRetrievalConfigParams,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.RetrievalConfigView>(
    `/api/v1/knowledge-bases/${param0}/retrieval-config`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Save Retrieval Config PUT /api/v1/knowledge-bases/${param0}/retrieval-config */
export async function knowledgeBasesSaveRetrievalConfig(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesSaveRetrievalConfigParams,
  body: API.UpdateRetrievalConfigRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.RetrievalConfigRevisionView>(
    `/api/v1/knowledge-bases/${param0}/retrieval-config`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** Run Retrieval Test POST /api/v1/knowledge-bases/${param0}/retrieval-tests */
export async function knowledgeBasesRunRetrievalTest(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.knowledgeBasesRunRetrievalTestParams,
  body: API.RetrievalTestRequest,
  options?: { [key: string]: any }
) {
  const { knowledgeBaseId: param0, ...queryParams } = params;
  return request<API.RetrievalTestResponse>(
    `/api/v1/knowledge-bases/${param0}/retrieval-tests`,
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
