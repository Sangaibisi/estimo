import { EligibilityController } from "./EligibilityController";

/** Bayi ekranında kampanya taksit seçeneklerini gösteren bileşen. */
export const CampaignBanner = ({ subscriberId }: { subscriberId: string }) => {
  return <div data-subscriber={subscriberId}>Kampanya taksit seçenekleri</div>;
};
