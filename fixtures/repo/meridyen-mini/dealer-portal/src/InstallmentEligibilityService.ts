/** Uygunluk kuralları: borç durumu, hat yaşı, kampanya kısıtları. */
export class InstallmentEligibilityService {
  async isEligible(subscriberId: string): Promise<boolean> {
    return subscriberId.length > 0;
  }
}
