import time
import os

'''
DEBUG_MODE == True is intended for testing code, while 
DEBUG_MODE == False is intended to enable faster training and inference
'''
DEBUG_MODE = True
import numpy as np
import torch

if DEBUG_MODE:
    np.random.seed(0)
    torch.manual_seed(0)
    torch.autograd.set_detect_anomaly(True)
    torch.autograd.profiler.profile(True)
    torch.backends.cudnn.benchmark = False
else:
    torch.autograd.set_detect_anomaly(False)
    torch.autograd.profiler.profile(False)
    torch.backends.cudnn.benchmark = True

from torch.utils.data import DataLoader
from torchvision import transforms
from torch.cuda.amp import GradScaler

torch.set_printoptions(linewidth=120)
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm
import yaml

from nutrition5k.dataset import Rescale, ToTensor, Nutrition5kDataset
from nutrition5k.model import Nutrition5kModel
from nutrition5k.train_utils import run_epoch
from nutrition5k.utils import parse_args

if __name__ == '__main__':
    # parse arguments
    args = parse_args()

    with open(args.config_path, 'r') as ymlfile:
        config = yaml.safe_load(ymlfile)

    transformed_dataset = Nutrition5kDataset(config['dataset_dir'], transform=transforms.Compose(
        [Rescale((299, 299)), ToTensor()]))

    n_videos = len(transformed_dataset)
    train_size = int(config['split']['train'] * n_videos)
    val_size = int(config['split']['validation'] * n_videos)
    test_size = n_videos - train_size - val_size

    train_set, val_set, test_set = torch.utils.data.random_split(transformed_dataset, [train_size, val_size, test_size])
    epoch_phases = ['train', 'val']
    dataloaders = {
        'train': DataLoader(train_set, batch_size=config['batch_size'], shuffle=True,
                            num_workers=config['dataset_workers'], pin_memory=True),
        'val': DataLoader(val_set, batch_size=config['batch_size'], shuffle=False,
                          num_workers=config['dataset_workers'], pin_memory=True),
        'test': DataLoader(val_set, batch_size=config['batch_size'], shuffle=False,
                           num_workers=config['dataset_workers'], pin_memory=True)
    }

    # Detect if we have a GPU available
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    model = Nutrition5kModel().to(device)
    # Start training from a checkpoint
    if config['start_checkpoint']:
        model.load_state_dict(torch.load(config['start_checkpoint']))

    optimizer = torch.optim.RMSprop(model.parameters(), lr=config['learning_rate'])
    criterion = torch.nn.L1Loss()
    comment = f' batch_size = {config["batch_size"]} lr = {config["learning_rate"]}'
    tensorboard = SummaryWriter(comment=comment)

    torch.save(dataloaders['test'], os.path.join(tensorboard.log_dir, 'test_loader.pt'))

    best_model_path = None

    if config['mixed_precision_enabled']:
        scaler = GradScaler()
    else:
        scaler = None

    since = time.time()
    best_val_loss = np.inf
    best_training_loss = np.inf
    for epoch in tqdm(range(config['epochs'])):
        training_loss = None
        val_loss = None
        optimizer.zero_grad()
        for phase in epoch_phases:
            if phase == 'train':
                model.train()
            else:
                model.eval()
            results = run_epoch(model, criterion, dataloaders[phase], device, phase, config['prediction_threshold'],
                                config['mixed_precision_enabled'], optimizer=optimizer, scaler=scaler,
                                gradient_acc_steps=config['gradient_acc_steps'])
            if phase == 'train':
                training_loss = results['average loss']
                '''
                for name, weight in model.named_parameters():
                    tensorboard.add_histogram(name, weight, epoch)
                    tensorboard.add_histogram(f'{name}.grad', weight.grad, epoch)
                '''
            else:
                val_loss = results['average loss']

            tensorboard.add_scalar('{} loss'.format(phase), results['average loss'], epoch)
            tensorboard.add_scalar('{} mass prediction accuracy'.format(phase), results['mass prediction accuracy'],
                                   epoch)
            tensorboard.add_scalar('{} calorie prediction accuracy'.format(phase),
                                   results['calorie prediction accuracy'], epoch)
            print('Epoch {} {} loss: {:.4f}'.format(epoch, phase, results['average loss']))

        if (val_loss < best_val_loss) or (not config['save_best_model_only']):
            torch.save(model.state_dict(), os.path.join(tensorboard.log_dir, 'epoch_{}.pt'.format(epoch)))
            best_val_loss = val_loss
        if training_loss < best_val_loss:
            best_training_loss = training_loss
    time_elapsed = time.time() - since
    print('Training complete in {:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))

    tensorboard.add_hparams(
        {'learning rate': config['learning_rate'], 'batch size': config['batch_size']},
        {
            'best training loss': best_training_loss,
            'best validation loss': best_val_loss
        },
    )
    tensorboard.close()
