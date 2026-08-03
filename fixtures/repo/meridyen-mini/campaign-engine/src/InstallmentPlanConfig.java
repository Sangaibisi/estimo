package com.meridyen.campaign;

/** Taksit sayısı ve komisyon oranı konfigürasyonu (kampanya bazında). */
public record InstallmentPlanConfig(int months, double commissionRate) {
}
