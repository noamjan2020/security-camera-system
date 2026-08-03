package com.noamjan.homeguard.data

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface PairingApi {
    @POST("pair/claim") suspend fun claim(@Body request: PairClaimRequest): PairClaimResponse
}

interface AgentApi {
    @GET("health") suspend fun health(): HealthResponse
    @POST("push/register") suspend fun registerPushToken(@Body request: PushRegistrationRequest): PushRegistrationResponse
    @GET("state") suspend fun state(): StateResponse
    @GET("events") suspend fun events(@Query("minutes") minutes: Int = 15, @Query("limit") limit: Int = 100): List<EventRecord>
    @GET("events/{id}") suspend fun event(@Path("id") id: String): EventRecord
    @POST("events/{id}/viewed") suspend fun markViewed(@Path("id") id: String): Map<String, Boolean>
    @DELETE("events/{id}") suspend fun deleteEvent(@Path("id") id: String)
    @GET("events/{id}/image") suspend fun eventImage(@Path("id") id: String): ResponseBody
    @GET("snapshot") suspend fun snapshot(): ResponseBody
    @POST("privacy/pause") suspend fun pauseCamera(): StateResponse
    @POST("privacy/resume") suspend fun resumeCamera(): StateResponse

    @Multipart
    @POST("audio/upload")
    suspend fun uploadAudio(@Part file: MultipartBody.Part): AudioUploadResponse

    @POST("audio/play") suspend fun playAudio(@Body request: PlaybackRequest): PlaybackReceipt
    @POST("audio/stop") suspend fun stopAudio(): PlaybackReceipt
    @GET("audio/receipt/{id}") suspend fun playbackReceipt(@Path("id") id: String): Map<String, String>
    @GET("logs/tail") suspend fun logs(@Query("lines") lines: Int = 300): LogsResponse
}
